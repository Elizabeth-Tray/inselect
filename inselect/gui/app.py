import numpy as np
import os
import json
import cv2

from functools import wraps
from pathlib import Path

from PySide import QtCore, QtGui

import inselect.settings

from inselect.lib import utils
from inselect.lib.document import InselectDocument
from inselect.lib.inselect_error import InselectError
from inselect.lib.qt_util import qimage_of_bgr
from inselect.lib.segment import segment_edges, segment_grabcut
from inselect.lib.utils import debug_print

from inselect.gui.help_dialog import HelpDialog
from inselect.gui.tabs.boxes import BoxesPage
from inselect.gui.tabs.metadata import MetadataPage
from inselect.workflow.ingest import ingest_image

class WorkerThread(QtCore.QThread):
    results = QtCore.Signal(list, np.ndarray)

    def __init__(self, image, resegment_window, selected=None, parent=None):
        super(WorkerThread, self).__init__(parent)
        self.image = image
        self.resegment_window = resegment_window
        self.selected = selected

    def run(self):
        if self.resegment_window:
            seeds = self.selected.seeds()
            rects, display = segment_grabcut(self.image, seeds=seeds,
                                             window=self.resegment_window)
        else:
            rects, display = segment_edges(self.image,
                                           window=None,
                                           resize=(5000, 5000),
                                           variance_threshold=100,
                                           size_filter=1)
        self.results.emit(rects, display)


def report_to_user(f):
    """A decorator for class methods that reports exceptions to the user
    """
    @wraps(f)
    def wrapper(self, *args, **kwargs):
        try:
            return f(self, *args, **kwargs)
        except Exception as e:
            QtGui.QMessageBox.critical(self, u'An error occurred',
                u'An error occurred:\n{0}'.format(e))
            raise e
    return wrapper


class InselectMainWindow(QtGui.QMainWindow):
    FILE_FILTER = "inselect files (*{0})".format(InselectDocument.EXTENSION)

    def __init__(self, app, filename=None):
        super(InselectMainWindow, self).__init__()
        self.app = app

        # Top-level container
        self.tabs = QtGui.QTabWidget(self)
        self.tabs.currentChanged.connect(self.tab_changed)
        self.setCentralWidget(self.tabs)

        # First tab - boxes view
        boxes = BoxesPage(self)
        self.tabs.addTab(boxes, 'Boxes')
        self.scene = boxes.scene
        self.segment_scene = boxes.segment_scene
        self.sidebar = boxes.sidebar
        self.splitter = boxes
        self.view = boxes.view

        # Second tab - metadata
        self.tabs.addTab(MetadataPage(), 'Metadata')

        self.padding = 0
        self.segment_display = None
        self.segment_image_visible = False

        self.create_actions()
        self.create_menus()

        self.resize(500, 500)

        self.worker = self.progressDialog = None

        # TODO LH Remove the need for empty image
        # A QImage that is shown when no document is open
        self.empty_image = QtGui.QImage(500, 500, QtGui.QImage.Format_RGB32)
        self.empty_image.fill(0xffffff)

        self.empty_document()

        self.showMaximized()
        self.splitter.setSizes([800, 100])
        self.show()

        if filename:
            self.open_document(filename)

        # TODO LH Why is this here and not in create_actions?
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+Q"), self, self.close)

    def tab_changed(self, index):
        if 0==index:
            debug_print('Boxes tab')
        else:
            debug_print('Metadata tab')

    @report_to_user
    def new_document(self):
        debug_print('new_document')

        self.close_document()

        # Source image
        folder = inselect.settings.get("working_directory")
        source, selected_filter = QtGui.QFileDialog.getOpenFileName(
                self, "Choose image for the new inselect document", folder,
                filter='Images (*.tiff *.png *.jpeg *.jpg)')

        if source:
            source = Path(source)
            doc = ingest_image(source, source.parent)
            self.open_document(doc.document_path)
            QtGui.QMessageBox.information(self, "Document created",
                'New inselect document [{0}] created in [{1}]'.format(doc.document_path.stem, doc.document_path.parent))

    @report_to_user
    def open_document(self, filename=None):
        debug_print('open_document', '[{0}]'.format(str(filename)))

        if not filename:
            folder = inselect.settings.get("working_directory")
            filename, _ = QtGui.QFileDialog.getOpenFileName(
                self, "Open", folder, self.FILE_FILTER)

        if filename:
            filename = Path(filename)
            document = InselectDocument.load(filename)
            inselect.settings.set_value('working_directory', str(filename.parent))

            if document.thumbnail:
                debug_print('Will display thumbnail')
                image_array = document.thumbnail.array
            else:
                debug_print('Will display full-res scan')
                image_array = document.scanned.array

            qimage = qimage_of_bgr(image_array)

            # Setup GUI actions
            w, h = qimage.width(), qimage.height()

            # Update the graphics scene, segment scene and sidebar elements
            self.segment_scene.empty()
            self.sidebar.clear()
            self.scene.set_image(qimage)
            self.segment_scene.set_size(w, h)

            self.document = document
            self.image_array = image_array
            self.qimage = qimage
            self.document_path = filename

            # TODO LH Prefer setWindowFilePath to setWindowTitle?
            self.setWindowTitle(u"inselect [{0}]".format(self.document_path.stem))

            for item in document.items:
                rect = item['rect']
                self.segment_scene.add_normalized(
                    rect.topleft, rect.bottomright, item['fields']
                )

            self.sync_ui()

    @report_to_user
    def save_document(self):
        debug_print('save_document')
        items = []

        for segment in self.segment_scene.segments():
           items.append({
               'rect': [segment.left(normalized=True),
                        segment.top(normalized=True),
                        segment.width(normalized=True),
                        segment.height(normalized=True)],
               'fields': segment.fields()
               })
        self.document.set_items(items)
        self.document.save()
        res = QtGui.QMessageBox.question(self, 'Write cropped specimen images?',
            'Write cropped specimen images?', QtGui.QMessageBox.No,
            QtGui.QMessageBox.Yes)
        if res==QtGui.QMessageBox.Yes:
            self.document.save_crops()

    @report_to_user
    def close_document(self):
        debug_print('close_document')
        # TODO LH If not dirty or dirty and user saved

        self.empty_document()

    @report_to_user
    def empty_document(self):
        """Creates an empty document
        """
        debug_print('empty_document')
        self.document = None

        self.scene.set_image(self.empty_image)
        self.qimage = self.empty_image
        self.image_array = None
        self.segment_display = None
        self.segment_image_visible = False

        # TODO LH Prefer setWindowFilePath to setWindowTitle?
        self.setWindowTitle("inselect")

        self.view.delete_all_boxes()

        self.sync_ui()

        # TODO LH Default zoom

    @report_to_user
    def zoom_in(self):
        self.view.zoom(1)

    @report_to_user
    def zoom_out(self):
        self.view.zoom(-1)

    @report_to_user
    def about(self):
        QtGui.QMessageBox.about(
            self,
            inselect.settings.get('about_label'),
            inselect.settings.get('about_text')
        )

    @report_to_user
    def help(self):
        """Open the help dialog"""
        d = HelpDialog(self)
        d.exec_()

    @report_to_user
    def worker_finished(self, rects, display):
        debug_print('worker_finished')
        worker, self.worker = self.worker, None
        self.progressDialog.hide()
        self.progressDialog = None

        self.toggle_segment_action.setEnabled(True)
        window = worker.resegment_window
        if window:
            if self.segment_display is None:
                h, w = self.image_array.shape[:2]
                self.segment_display = np.zeros((h, w, 3), dtype=np.uint8)
            x, y, w, h = window
            self.segment_display[y:y+h, x:x+w] = display
            # removes the selected box before replacing it with resegmentations
            self.segment_scene.remove(worker.selected)
        else:
            self.view.delete_all_boxes()
            self.segment_display = display.copy()

        if self.segment_image_visible:
            self.display_image(self.segment_display)
        # add detected boxes
        for rect in rects:
            x, y, w, h = rect[:4]
            x -= w * self.padding
            y -= w * self.padding
            w += 2 * w * self.padding
            h += 2 * h * self.padding
            self.segment_scene.add((x, y), (x + w, y + h))

        self.sync_ui()

    @report_to_user
    def segment(self):
        # TODO LH Should be modal
        # TODO LH Allow cancel
        # TODO LH Possible to show progress?

        if self.worker:
            raise InselectError('Reenter segment()')
        else:
            debug_print('segment')
            self.toggle_segment_action.setEnabled(True)
            self.progressDialog = QtGui.QProgressDialog(self)
            self.progressDialog.setWindowTitle("Segmenting...")
            self.progressDialog.setCancelButton(None)
            self.progressDialog.setValue(0)
            self.progressDialog.setMaximum(0)
            self.progressDialog.setMinimum(0)
            self.progressDialog.show()
            resegment_window = None
            # if object selected, resegment the window
            selected = self.scene.selected_segments()
            if selected:
                selected = selected[0]
                window_rect = selected.get_q_rect_f()
                p = window_rect.topLeft()
                resegment_window = [p.x(), p.y(), window_rect.width(),
                                    window_rect.height()]
            self.worker = WorkerThread(self.image_array, resegment_window, selected)
            self.worker.results.connect(self.worker_finished)
            self.worker.start()

    @report_to_user
    def select_all(self):
        self.view.select_all()

    @report_to_user
    def select_none(self):
        self.view.select_none()

    @report_to_user
    def display_image(self, image):
        """Displays an image in the user interface.

        Parameters
        ----------
        image : np.ndarray, QtCore.QImage
            Image to be displayed in viewer.
        """
        if isinstance(image, np.ndarray):
            image = qimage_of_bgr(image)
        self.scene._image_item.setPixmap(QtGui.QPixmap.fromImage(image))

    @report_to_user
    def toggle_padding(self):
        """Action method to toggle box padding."""
        if self.padding == 0:
            self.padding = 0.05
        else:
            self.padding = 0

    @report_to_user
    def toggle_segment_image(self):
        """Action method to switch between display of segmentation image and
        actual image.
        """
        self.segment_image_visible = not self.segment_image_visible
        if self.segment_image_visible:
            image = self.segment_display
        else:
            image = self.qimage
        self.display_image(image)

    def create_actions(self):
        # File menu
        self.new_action = QtGui.QAction(
            "&New...", self, shortcut="ctrl+N", triggered=self.new_document)
        self.open_action = QtGui.QAction(
            self.style().standardIcon(QtGui.QStyle.SP_DialogOpenButton),
            "&Open...", self, shortcut="ctrl+O", triggered=self.open_document)
        self.save_action = QtGui.QAction(
            self.style().standardIcon(QtGui.QStyle.SP_DialogSaveButton),
            "&Save", self, shortcut="ctrl+s", enabled=False,
            triggered=self.save_document)
        self.close_action = QtGui.QAction(
            "&Close", self, shortcut="ctrl+w", triggered=self.close_document)
        self.exit_action = QtGui.QAction(
            "E&xit", self, shortcut="alt+f4", triggered=self.close)
        # TODO LH Also Ctrl+Q?

        # Edit menu
        self.toggle_padding_action = QtGui.QAction(
            "&Toggle padding", self, shortcut="", enabled=True,
            statusTip="Toggle padding", checkable=True,
            triggered=self.toggle_padding)
        self.select_all_action = QtGui.QAction(
            "Select &All", self, shortcut="ctrl+A", triggered=self.select_all)
        self.select_none_action = QtGui.QAction(
            "Select &None", self, shortcut="ctrl+D", triggered=self.select_none)
        self.segment_action = QtGui.QAction(
            self.style().standardIcon(QtGui.QStyle.SP_BrowserReload),
            "&Segment", self, shortcut="f5", enabled=False,
            statusTip="Segment",
            triggered=self.segment)

        # View menu
        self.zoom_in_action = QtGui.QAction(
            self.style().standardIcon(QtGui.QStyle.SP_ArrowUp),
            "Zoom &In", self, enabled=False, shortcut="Ctrl++",
            triggered=self.zoom_in)
        self.zoom_out_action = QtGui.QAction(
            self.style().standardIcon(QtGui.QStyle.SP_ArrowDown),
            "Zoom &Out", self, enabled=False, shortcut="Ctrl+-",
            triggered=self.zoom_out)
        self.toggle_segment_action = QtGui.QAction(
            "&Display segmentation", self, shortcut="f3", enabled=False,
            statusTip="Display segmentation image", checkable=True,
            triggered=self.toggle_segment_image)

        # Help menu
        self.about_action = QtGui.QAction("&About", self, triggered=self.about)
        self.help_action = QtGui.QAction("&Help", self, triggered=self.help)

    def create_menus(self):
        self.toolbar = self.addToolBar("Edit")
        self.toolbar.addAction(self.open_action)
        self.toolbar.addAction(self.save_action)
        self.toolbar.addAction(self.segment_action)
        self.toolbar.addAction(self.zoom_in_action)
        self.toolbar.addAction(self.zoom_out_action)
        self.toolbar.setToolButtonStyle(QtCore.Qt.ToolButtonTextUnderIcon)

        self.fileMenu = QtGui.QMenu("&File", self)
        self.fileMenu.addAction(self.new_action)
        self.fileMenu.addAction(self.open_action)
        self.fileMenu.addAction(self.save_action)
        self.fileMenu.addAction(self.close_action)
        self.fileMenu.addSeparator()
        self.fileMenu.addAction(self.exit_action)

        self.editMenu = QtGui.QMenu("&Edit", self)
        self.editMenu.addAction(self.toggle_padding_action)
        self.editMenu.addAction(self.select_all_action)
        self.editMenu.addAction(self.select_none_action)
        self.fileMenu.addSeparator()
        self.editMenu.addAction(self.segment_action)

        self.viewMenu = QtGui.QMenu("&View", self)
        self.viewMenu.addAction(self.zoom_in_action)
        self.viewMenu.addAction(self.zoom_out_action)
        self.viewMenu.addAction(self.toggle_segment_action)

        self.helpMenu = QtGui.QMenu("&Help", self)
        self.helpMenu.addAction(self.help_action)
        self.helpMenu.addAction(self.about_action)

        self.menuBar().addMenu(self.fileMenu)
        self.menuBar().addMenu(self.editMenu)
        self.menuBar().addMenu(self.viewMenu)
        self.menuBar().addMenu(self.helpMenu)

    def sync_ui(self):
        """Synchronise the user interface with the application state
        """
        if self.document:
            self.toggle_segment_action.setEnabled(self.segment_display is not None)
            self.segment_action.setEnabled(True)
            self.zoom_in_action.setEnabled(True)
            self.zoom_out_action.setEnabled(True)
            self.save_action.setEnabled(True)
            self.close_action.setEnabled(True)
        else:
            self.toggle_segment_action.setEnabled(False)
            self.segment_action.setEnabled(False)
            self.zoom_in_action.setEnabled(False)
            self.zoom_out_action.setEnabled(False)
            self.save_action.setEnabled(False)
            self.close_action.setEnabled(False)

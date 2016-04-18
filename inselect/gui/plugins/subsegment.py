import numpy as np

from PySide.QtGui import QIcon, QMessageBox

from inselect.lib.segment import segment_grabcut
from inselect.lib.rect import Rect
from inselect.lib.utils import debug_print

from .plugin import Plugin


class SubsegmentPlugin(Plugin):
    NAME = 'Subsegment box'
    DESCRIPTION = ('Will subsegment and replace the selected box using seed '
                   'points.')

    def __init__(self, document, parent):
        super(SubsegmentPlugin, self).__init__()
        self.rects = self.display = None
        self.document = document
        self.parent = parent

    @classmethod
    def icon(cls):
        return QIcon(':/data/subsegment_icon.png')

    def can_be_run(self):
        # TODO LH Fix this horrible, horrible, horrible, horrible, horrible hack
        selected = self.parent.view_object.selectedIndexes()
        items_of_indexes = self.parent.view_graphics_item.items_of_indexes
        item = items_of_indexes(selected).next() if 1 == len(selected) else None
        seeds = item.points_of_interest if item else None

        if not seeds or len(seeds) < 2:
            msg = ('Please select exactly one box that contains at least two '
                   'seed points')
            QMessageBox.warning(self.parent, "Unable to subsegment", msg)
            return False
        else:
            self.row = selected[0].row()
            self.seeds = seeds
            return True

    def __call__(self, progress):
        debug_print('SubsegmentPlugin.__call__')

        if self.document.thumbnail:
            debug_print('Subsegment will work on thumbnail')
            image = self.document.thumbnail
        else:
            debug_print('Segment will work on full-res scan')
            image = self.document.scanned

        # Perform the subsegmentation
        items = self.document.items
        row = self.row
        window = image.from_normalised([items[row]['rect']]).next()

        # Points as a list of tuples, with coordinates relative to
        # the top-left of the sub-segmentation window
        seeds = [(p.x(), p.y()) for p in self.seeds]

        rects, display = segment_grabcut(image.array, window, seeds)

        # Normalised Rects
        rects = list(Rect(*map(lambda v: int(round(v)), rect[:4])) for rect in rects)
        rects = image.to_normalised(rects)

        # Padding of one percent of height and width
        rects = (r.padded(percent=1) for r in rects)

        # Constrain rects to be within image
        rects = list(r.intersect(Rect(0.0, 0.0, 1.0, 1.0)) for r in rects)

        # Copy any existing metadata, rotation etc to the new items, update with
        # new rects and replace the existing item
        existing = items[row]
        new_items = [None] * len(rects)
        for index, rect in enumerate(rects):
            new_items[index] = existing.copy()
            new_items[index]['rect'] = rect
        items[row:(1+row)] = new_items

        # Segmentation image
        h, w = image.array.shape[:2]
        display_image = np.zeros((h, w, 3), dtype=np.uint8)

        x, y, w, h = window
        display_image[y:y+h, x:x+w] = display

        self.items, self.display = items, display_image

        debug_print(
            'SegmentPlugin.__call__ exiting. Found [{0}] boxes'.format(len(rects))
        )

# Temporary solution until I get round to writing a makefile

set -e  # Exit on failure

VERSION=`python inselect.py --version 2>&1 | sed 's/inselect.py //g'`

echo Building Inselect $VERSION

echo Clean
find . -name "*pyc" -print0 | xargs -0 rm -rf
find . -name __pycache__ -print0 | xargs -0 rm -rf
rm -rf cover

echo Tests
nosetests --with-coverage --cover-html --cover-inclusive --cover-erase --cover-tests --cover-package=inselect inselect

echo Source build
rm -rf dist
./setup.py sdist
mv dist/inselect-$VERSION.tar.gz .

if [[ "$OSTYPE" == "darwin"* ]]; then
    # Clean existing build files
    rm -rf build dist
    pyinstaller --clean inselect.spec
    for script in export_metadata ingest read_barcodes save_crops segment; do
        rm -rf $script.spec
        pyinstaller --onefile --icon=data/inselect.icns inselect/workflow/$script.py
    done
    # Add a few items to the PropertyList file generated by PyInstaller
    python -m bin.plist dist/inselect.app/Contents/Info.plist
    # Example document
    install -c -m 644 data/Plecoptera_Accession_Drawer_4.jpg dist/
    install -c -m 644 data/Plecoptera_Accession_Drawer_4.inselect dist/
    # Remove the directory containing the console app (the windowed app is in inselect.app)
    rm -rf dist/inselect
    rm -rf inselect-$VERSION.dmg
    hdiutil create inselect-$VERSION.dmg -volname inselect-$VERSION -srcfolder dist
fi

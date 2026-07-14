# Fusion Electronics port

This is an Autodesk Fusion Electronics port of
[hulryung/kicad-lcsc-manager](https://github.com/hulryung/kicad-lcsc-manager),
the original KiCad LCSC Manager plugin by
[hulryung](https://github.com/hulryung).

The Fusion add-in keeps the KiCad plugin's catalog workflow inside Autodesk Fusion:

- search LCSC/JLCPCB by part number, name, value, and package
- inspect stock, pricing metadata, product photos, symbol previews, and footprint previews
- import EasyEDA symbols, footprints, device metadata, and pin-to-pad connections
- preserve multi-unit symbols as separate Fusion gates
- update an existing local library without duplicating a component
- download the available STEP model beside the library

The generated library is an EAGLE 9.6.2-compatible `.lbr`, which Fusion Electronics imports natively.

## Install

Build the self-contained add-in:

```sh
./scripts/package-fusion.sh 0.1.0
```

Unzip `release/fusion-lcsc-manager-0.1.0.zip` and copy its
`LCSCManagerFusion` folder into Fusion's add-in directory:

- macOS: `~/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns/`
- Windows: `%AppData%\Autodesk\Autodesk Fusion 360\API\AddIns\`

Restart Fusion; the add-in loads at startup and places **LCSC Manager** in the global quick-access toolbar. If the button does not appear, open **Utilities → Scripts and Add-Ins**, select **LCSCManagerFusion**, and click **Run**.

If your Fusion installation uses a different add-in directory, use the **+**
menu in **Scripts and Add-Ins**, choose **Script or add-in from device**, and
select the unzipped `LCSCManagerFusion` folder.

For development, use the green **+** button in **Scripts and Add-Ins** and select `fusion/LCSCManagerFusion` from this repository. Install `requirements.txt` in `.venv` first; the add-in detects that environment when linked from the repository.

## Use

1. Open **LCSC Manager** from Fusion's quick-access toolbar.
2. Search and select a part.
3. Scroll through its complete symbol, footprint, product photo, stock, and metadata.
4. Choose a destination ending in `.lbr` and click **Import selected**.
5. In an Electronics design, open **Library Manager → Private Libraries → Import/restore Libraries**, select the generated `.lbr`, and activate it.

To share the library with a team, upload the `.lbr` through Fusion's Data Panel instead. Autodesk documents both workflows in [Import a complete electronics library](https://help.autodesk.com/cloudhelp/ENU/Fusion-ECAD/files/ECAD-IMPORT-LIB-TSK.htm).

You can also generate a library without opening Fusion:

```sh
PYTHONPATH=plugins python -m lcsc_manager.fusion C2040 C7950 \
  --output ~/Documents/Fusion\ 360/LCSC/lcsc_imported.lbr
```

## Fusion API limitation

As of July 2026, Autodesk's public Electronics API is preview-only and read-only for design and library content. It can inspect and export Electronics documents, but cannot create a component or mutate the open cloud library. See Autodesk's [Electronics API introduction](https://help.autodesk.com/cloudhelp/ENU/Fusion-360-API/files/ElectronicsIntro.htm).

Consequently, two steps remain native Fusion operations:

- import or refresh the generated `.lbr` through Library Manager
- attach the downloaded `<library-name>.3dmodels/<LCSC-ID>.step` file in the package editor

EAGLE's library format cannot represent every EasyEDA pad primitive exactly. The importer flags custom copper pads and plated slots when it has to use a rectangular or circular approximation.

Always verify generated symbols, pin mapping, footprints, and 3D alignment against the manufacturer's datasheet before fabrication.

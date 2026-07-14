# Fusion LCSC Manager

> This is an Autodesk Fusion Electronics port of
> [hulryung/kicad-lcsc-manager](https://github.com/hulryung/kicad-lcsc-manager),
> the original KiCad LCSC Manager plugin by
> [hulryung](https://github.com/hulryung).

Search LCSC/JLCPCB from Fusion, preview product images, symbols, and
footprints, then generate a Fusion-compatible electronics library and download
the available STEP model.

## Install

You need Autodesk Fusion, Git, and Python 3.

1. Clone the repository and install the add-in's Python dependency:

   **macOS**

   ```sh
   git clone https://github.com/nikokozak/fusion-lcsc-manager.git
   cd fusion-lcsc-manager
   python3 -m pip install --target fusion/LCSCManagerFusion/lib requests
   ```

   **Windows**

   ```powershell
   git clone https://github.com/nikokozak/fusion-lcsc-manager.git
   cd fusion-lcsc-manager
   py -3 -m pip install --target fusion\LCSCManagerFusion\lib requests
   ```

2. In Fusion, open **Utilities → Scripts and Add-Ins**.
3. Select the **Add-Ins** tab.
4. Click **+ → Script or add-in from device**.
5. Select the cloned `fusion/LCSCManagerFusion` folder.
6. Select **LCSCManagerFusion** in the list and click **Run**.
7. Open **LCSC Manager** from Fusion's quick-access toolbar.

Keep the cloned repository in place. Fusion links directly to that folder and
starts the add-in automatically on future launches.

## Use

1. Search by LCSC number, part name, value, or package.
2. Select a result to inspect its product image, symbol, footprint, pricing,
   and stock.
3. Choose an output path ending in `.lbr`.
4. Select the content to import and click **Import selected**.
5. In a Fusion Electronics design, open **Library Manager → Private
   Libraries → Import/restore Libraries**, select the generated `.lbr`, and
   activate it.

The default library is:

```text
~/Documents/Fusion 360/LCSC/lcsc_imported.lbr
```

When available, the STEP model is saved under
`lcsc_imported.3dmodels/<LCSC-ID>.step`. Attach it to the footprint in
Fusion's package editor.

## Update

```sh
cd fusion-lcsc-manager
git pull
```

Then stop and run the add-in again from **Scripts and Add-Ins**, or restart
Fusion.

## Troubleshooting

- **The add-in is not listed:** Link the `fusion/LCSCManagerFusion` folder
  again using **+ → Script or add-in from device**.
- **Python import error:** Repeat the `pip install --target` command from the
  installation section.
- **Old or broken interface:** Stop the add-in, restart Fusion, and run it
  again.
- **No EasyEDA CAD data:** That LCSC listing has no importable symbol or
  footprint. Test the installation with a known part such as `C2040`.

## Current limitations

- Fusion requires the generated `.lbr` to be imported through Library
  Manager.
- STEP models must be attached manually in the package editor.
- Some EasyEDA custom pads and plated slots require geometric approximations.

Always verify symbols, pin mapping, footprints, and 3D alignment against the
manufacturer's datasheet before fabrication.

See [FUSION.md](FUSION.md) for technical details and command-line usage.
For the original KiCad plugin and its installation instructions, use the
[upstream project](https://github.com/hulryung/kicad-lcsc-manager).

## Credits and license

The Fusion port is based on the original KiCad plugin by
[hulryung](https://github.com/hulryung). Conversion code also derives from
[easyeda2kicad.py](https://github.com/uPesy/easyeda2kicad.py) and
[JLC2KiCad_lib](https://github.com/TousstNicolas/JLC2KiCad_lib).

The plugin wrapper is MIT-licensed. Some bundled conversion code remains under
AGPL-3.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).

Report Fusion-port problems in the
[issue tracker](https://github.com/nikokozak/fusion-lcsc-manager/issues).

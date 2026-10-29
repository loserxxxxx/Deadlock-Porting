# Deadlock Porting

Windows desktop application for browsing Deadlock models and exporting them to Blender, GLB, or FBX.

The app includes character posing controls, separate hero props, model previews, Steam and Blender detection, existing-project imports, Discord Rich Presence, and signed updates. Props and objectives export without character control rigs. Map parts export individually.

## Requirements

- Windows x64
- A local Deadlock installation
- Blender 4.2 or newer

## Build

Install Python 3.12, Rust's MSVC toolchain, Visual Studio C++ Build Tools, and Microsoft WebView2. Node.js is needed only for frontend tests.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r port/requirements-bundled.txt
.\build-tauri.ps1
```

The portable executable is written to `dist/Deadlock Porting.exe`. The build downloads and verifies Python's embedded runtime and Microsoft's WebView2 installer. Runtime dependencies and exporter scripts are embedded into the executable. Game files and Blender are not bundled.

Bundled thumbnails are in `port/previews`. To rebuild them from an installed game, run `build-preview-pack.py` with the project Python environment before building.

## Tests

```powershell
node --test frontend/library.test.mjs frontend/updater.test.mjs
.\.venv\Scripts\python.exe port/test_installations.py
.\.venv\Scripts\python.exe port/test_blender_sessions.py
.\.venv\Scripts\python.exe port/test_project_export.py
.\.venv\Scripts\python.exe port/test_skinning.py
.\.venv\Scripts\python.exe port/test_vertex_colors.py
.\.venv\Scripts\python.exe port/test_previews.py
cargo test --manifest-path src-tauri/Cargo.toml updater::tests
cargo test --manifest-path src-tauri/Cargo.toml presence::tests
```

Blender integration tests require Blender and an exported scene. The worker round-trip test also requires installed game files. The live updater test is ignored by default.

## Source layout

- `frontend/`: model browser and export interface
- `src-tauri/`: native window, worker process, runtime packaging, Rich Presence, and updater
- `port/`: model decoder, Blender exporter, rigging, installation detection, and tests
- `package-runtime.py`: embedded runtime builder
- `prepare-release.py`: signed release artifacts

## Releases

Update the version in `src-tauri/Cargo.toml` and `src-tauri/tauri.conf.json`, then build the release. Install Python's `cryptography` package and set `DEADLOCK_UPDATE_SIGNING_KEY` to the private signing key file before running `prepare-release.py`.

The resulting executable, signed update manifest, and checksum are written to `dist/release`. Publish the executable under the manifest's `/downloads/` URL and the manifest at `/updates/windows.json` on the release host. The website source is maintained separately.

Only the public verification key is included here. Official releases must be signed with its matching private key. Forks should configure their own signing keys, release endpoint, Discord application ID, and branding.

## Data

Settings, cached previews, exports, and logs are stored under `%LOCALAPPDATA%/DeadlockPorting`. Existing-project imports create a backup before replacing a saved Blender file. Save and close the target project before importing.

## Development

Parts of the code and documentation were developed with AI assistance. The project direction, feature requirements, and design feedback came from the creator.

## Licensing

The Blender module declares GPL-3.0-or-later; its license is included in `port/deadlock_porting/LICENSE`. Dependencies retain their respective licenses. A project-wide license has not been selected. Deadlock and its assets belong to their respective rights holders. This is an independent project.

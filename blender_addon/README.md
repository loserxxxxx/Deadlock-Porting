# Deadlock Porting Live

Send models from the desktop app directly into an open Blender scene. Blender stays running, including when the project has unsaved changes or has never been saved.

## Install

1. In the app, select **Open Blender** and click **Get Blender add-on** to save the ZIP. The ZIP is also attached to GitHub releases.
2. In Blender 4.2 or newer, open **Edit → Preferences → Add-ons**.
3. Open the menu in the upper-right corner, choose **Install from Disk**, and select the ZIP.
4. Enable **Deadlock Porting Live**. No Blender restart is required.
5. In the app, refresh the connected-scene list and choose the open project.
6. Export a model. It is added at the current scene's 3D cursor in a new collection.

The 3D View sidebar has a **Deadlock Porting** tab with connection status and a disconnect button. Object or Pose Mode is required to receive an import. Imports wait while Blender is rendering or working in another mode; unclaimed requests expire rather than importing unexpectedly much later.

## Behavior

Rigs, control shapes, materials, packed textures, and separate props are appended from the finished export. Existing objects and scene settings are retained. The add-on does not save, reload, or replace the open project; save it in Blender when ready. The import is implemented as an undoable Blender operator.

If the active scene or project changes while an export is being prepared, the import is rejected and the standalone exported file remains available. Multiple Blender processes are listed separately. Each export uses the selected Blender instance's executable to prepare a compatible asset.

The bridge uses authenticated local files under `%LOCALAPPDATA%/DeadlockPorting/live`. It opens no network port and requires no account. Blender changes run on the main thread through application timers. Its extension manifest requests file access only.

## Build and test

Run `python build-blender-addon.py` from the repository root. It builds `package/DeadlockPorting-Blender-Addon.zip` and keeps the app and add-on protocol copies synchronized. `package-runtime.py` runs this step automatically before app builds.

`python port/test_live_blender.py` tests session freshness, authentication, stale-target checks, delivery receipts, and timeouts. `port/test_live_blender_scene.py` is the Blender-side integration-test driver; it creates its own project and checks that imported assets preserve unsaved work and the project file on disk.

Live import has been tested with Blender 5.2. The add-on requires Blender 4.2 or newer and is licensed GPL-3.0-or-later.

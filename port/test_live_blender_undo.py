import bpy,sys,os,uuid,time,tempfile
from pathlib import Path
root=Path(__file__).resolve().parents[1]
temporary=tempfile.TemporaryDirectory()
os.environ['DEADLOCK_LIVE_DATA']=str(Path(temporary.name)/'bridge')
sys.path.insert(0,str(root/'blender_addon'));import deadlock_porting_live as addon
from deadlock_porting_live.protocol import atomic_json,signature,fingerprint,read_json
bpy.ops.wm.read_factory_settings(use_empty=False)
bpy.data.objects['Cube'].location=(4,5,6);bpy.data.objects['Cube']['unsaved_work']='kept';bpy.context.scene.frame_set(17)
addon.register()
addon.start()
try:
 asset=Path(sys.argv[sys.argv.index('--')+1]).resolve();identifier=uuid.uuid4().hex
 request=dict(protocol=1,request_id=identifier,session_id=addon._session['id'],expected_scene=addon.scene_id(),expected_project='',asset=str(asset),sha256=fingerprint(asset),label='Wraith',expires=time.time()+30)
 request['signature']=signature(request,addon._session['token']);path=addon.root_path()/'queues'/addon._session['id']/'requests'/(identifier+'.json');atomic_json(path,request);addon.process_request(path)
 receipt=read_json(path.parent.parent/'receipts'/path.name);assert receipt['ok'],receipt
 assert any(c.get('deadlock_export') for c in bpy.context.scene.collection.children)
 assert bpy.ops.ed.undo.poll(),'Undo unavailable'
 bpy.ops.ed.undo()
 assert not any(c.get('deadlock_export') for c in bpy.context.scene.collection.children)
 assert tuple(bpy.data.objects['Cube'].location)==(4,5,6)
 assert bpy.data.objects['Cube']['unsaved_work']=='kept'
 assert bpy.context.scene.frame_current==17
 print('UNDO_VERIFIED: imported collection removed, unsaved edits and frame preserved')
finally:
 addon.unregister()
 temporary.cleanup()

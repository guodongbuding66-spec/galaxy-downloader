"""Capture the real composed Windows Tk application, never a drawn mockup."""
import json,sys,time
from pathlib import Path
from PIL import ImageGrab
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'local-engine'))
import entrypoint
import engine
out=Path(sys.argv[1] if len(sys.argv)>1 else 'qa');out.mkdir(parents=True,exist_ok=True)
app=engine.EngineWindow(None)
try:
 app.minsize(1000,650);app.geometry('1020x650+2+2');app.deiconify();app.lift();app.update_idletasks();app.update();time.sleep(.7);app.update()
 x,y,w,h=app.winfo_rootx(),app.winfo_rooty(),app.winfo_width(),app.winfo_height()
 ImageGrab.grab(bbox=(x,y,x+w,y+h),all_screens=True).save(out/'native-workbench.png')
 assert getattr(app,'_original_images_button',None) is not None
 (out/'native-runtime.json').write_text(json.dumps({'nativeWindowCreated':True,'width':w,'height':h,'screenshot':'native-workbench.png','mock':False},indent=2))
finally:app.destroy()

#!/usr/bin/env python3
"""Download upstream public samples at best quality using Galaxy's actual runner.
PASS requires a final file, ffprobe streams and full FFmpeg decode; not just a
successful exit. Budget limits never trigger a silent low-resolution retry.
"""
from __future__ import annotations
import argparse,concurrent.futures,importlib.util,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'local-engine'))
import external_ytdlp
PLATFORMS=['youtube','bilibili','douyin','tiktok','instagram','x','facebook','vimeo','reddit','dailymotion','weibo','xiaohongshu','telegram','pinterest','streamable','kuaishou','threads','wechat','niconico','tumblr','vk','okru','twitch','soundcloud','bluesky','rumble','snapchat','coub','imgur','odysee','rutube']
def fixtures():
 spec=importlib.util.spec_from_file_location('galaxy_fixture_source',ROOT/'scripts/platform-smoke.py');module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
 items={k:(v[0].url if v else None) for k,v in module.build_fixture_candidates().items()}
 from yt_dlp.extractor.facebook import FacebookIE
 items['facebook']=next((t['url'] for t in FacebookIE._TESTS if 'url' in t and 'facebook.com' in t['url']),None)
 return items

def classify(error):
 lower=error.lower()
 if any(w in lower for w in ['egress','network is unreachable','name resolution','name or service not known','certificate_verify_failed','certificate verify failed']):return 'NETWORK_BLOCKED'
 if any(w in lower for w in ['cookies','sign in','login','log in','authentication','private','geo restricted','not available in your country']):return 'ACCESS_REQUIRED'
 if any(w in lower for w in ['403','429','access denied','captcha','tls fingerprint','bot']):return 'ACCESS_BLOCKED'
 if 'budget' in lower or 'cancelled' in lower:return 'TEST_BUDGET'
 return 'FAILED'

def run_one(platform,url,out,timeout):
 folder=out/platform;folder.mkdir(exist_ok=True);record={'platform':platform,'url':url,'status':'NOT_TESTED','qualityPolicy':'bv+ba/b (best; no resolution cap)','scope':'one upstream public sample, no account/cookies'}
 if not url:record['reason']='No public fixture supplied by upstream';return record
 started=time.monotonic();log=[]
 def cancelled():
  if time.monotonic()-started>timeout:return True
  size=0
  for p in folder.iterdir():
   try:size+=p.stat().st_size if p.is_file() else 0
   except FileNotFoundError:continue
  return size>250*1024**2
 try:
  media=external_ytdlp.download_with_external_ytdlp(Path(shutil.which('yt-dlp')),url,format_selector='bv+ba/b',output_template=str(folder/'media.%(ext)s'),ffmpeg_location=Path(shutil.which('ffmpeg')).parent,browser='none',playlist=False,include_subtitle=False,subtitle_language=None,include_cover=False,cancelled=cancelled,on_progress=lambda *a:None,on_status=log.append)
  if not media:raise RuntimeError('No final media file')
  probe=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(media)],capture_output=True,text=True,timeout=30)
  if probe.returncode:raise RuntimeError(probe.stderr)
  info=json.loads(probe.stdout);streams=info.get('streams',[])
  if not streams:raise RuntimeError('No playable media streams')
  decode=subprocess.run(['ffmpeg','-v','error','-i',str(media),'-map','0:v?','-map','0:a?','-f','null','-'],capture_output=True,text=True,timeout=90)
  if decode.returncode:raise RuntimeError('Full decode failed: '+decode.stderr[-800:])
  video=next((s for s in streams if s.get('codec_type')=='video'),{})
  record.update(status='PASS',file=media.name,bytes=media.stat().st_size,width=video.get('width'),height=video.get('height'),duration=info.get('format',{}).get('duration'),codecs=[s.get('codec_name') for s in streams],fullDecode=True)
  if video:
   frame=folder/'frame.jpg';snap=subprocess.run(['ffmpeg','-v','error','-ss','0.5','-i',str(media),'-frames:v','1','-update','1',str(frame),'-y'],capture_output=True,text=True,timeout=20)
   if snap.returncode==0:record['frame']=str(frame.relative_to(out))
  (folder/'ffprobe.json').write_text(json.dumps(info,ensure_ascii=False,indent=2))
 except Exception as exc:record.update(status=classify(str(exc)),reason=str(exc)[-1600:])
 record['elapsedSeconds']=round(time.monotonic()-started,2)
 (folder/'download.log').write_text('\n'.join(log)+'\n'+str(record.get('reason','')),encoding='utf-8');(folder/'result.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({k:record.get(k) for k in ['platform','status','width','height','elapsedSeconds']},ensure_ascii=False),flush=True)
 return record

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--platforms',default=','.join(PLATFORMS));parser.add_argument('--timeout',type=int,default=85);parser.add_argument('--workers',type=int,default=5);parser.add_argument('--system-ca',action='store_true',help='Use system CA store while retaining certificate verification');args=parser.parse_args()
 if not shutil.which('yt-dlp'):parser.error('yt-dlp executable must be on PATH')
 out=args.output.resolve();out.mkdir(parents=True,exist_ok=True);source=fixtures();results=[]
 if args.system_ca:
  original=external_ytdlp.build_external_command
  def with_system_ca(*values,**options):
   command=original(*values,**options);command[1:1]=['--compat-options','no-certifi'];return command
  external_ytdlp.build_external_command=with_system_ca
 with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
  jobs=[pool.submit(run_one,name,source.get(name),out,args.timeout) for name in args.platforms.split(',')]
  for future in concurrent.futures.as_completed(jobs):
   results.append(future.result());(out/'results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
 summary={'testedAt':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'runtime':sys.platform,'systemCaStore':args.system_ca,'ytDlpVersion':subprocess.check_output(['yt-dlp','--version'],text=True).strip(),'qualityPolicy':'best video + best audio, muxed fallback; no low-resolution retry','sampleBudgetSeconds':args.timeout,'sampleBudgetBytes':250*1024**2,'results':sorted(results,key=lambda r:r['platform'])}
 (out/'acceptance.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print('LIVE_ACCEPTANCE_FINISHED',flush=True)
if __name__=='__main__':main()

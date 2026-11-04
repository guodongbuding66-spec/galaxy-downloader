import io,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'local-engine'))
import external_ytdlp as e
class Process:
 def __init__(self,lines):self.stdout=io.StringIO(lines)
 def poll(self):return 0
 def wait(self):return 0
class CompletionTests(unittest.TestCase):
 def run_fake(self,lines,archive=None):
  with patch.object(e.subprocess,'Popen',return_value=Process(lines)):
   return e._run_external_once(Path('yt-dlp'),'https://example.com/video',format_selector='bv+ba/b',output_template='ignored',ffmpeg_location=None,browser='none',playlist=False,include_subtitle=False,subtitle_language=None,include_cover=False,collection_mode='single',selected_items=None,download_archive=archive,cancelled=lambda:False,on_progress=lambda *a:None,on_status=lambda *a:None)
 def test_exit_zero_without_file_is_failure(self):
  with self.assertRaises(e.ExternalYtDlpError):self.run_fake('[info] No matching videos\n')
 def test_nonexistent_reported_file_is_failure(self):
  with self.assertRaises(e.ExternalYtDlpError):self.run_fake(e.FILE_PREFIX+'/nonexistent/result.mp4\n')
 def test_empty_and_partial_files_are_failure(self):
  with tempfile.TemporaryDirectory() as d:
   for name,content in [('empty.mp4',b''),('video.part',b'bytes')]:
    p=Path(d)/name;p.write_bytes(content)
    with self.assertRaises(e.ExternalYtDlpError):self.run_fake(e.FILE_PREFIX+str(p)+'\n')
 def test_final_file_is_accepted(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'result.mp4';p.write_bytes(b'completed-container')
   self.assertEqual(self.run_fake(e.FILE_PREFIX+str(p)+'\n'),p)
 def test_archive_skip_requires_explicit_archive(self):
  line='[download] abc: has already been recorded in the archive\n'
  self.assertIsNone(self.run_fake(line,Path('archive.txt')))
  with self.assertRaises(e.ExternalYtDlpError):self.run_fake(line)
if __name__=='__main__':unittest.main()

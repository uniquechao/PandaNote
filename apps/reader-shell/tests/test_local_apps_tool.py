import importlib.util,tempfile,unittest,os
from pathlib import Path
spec=importlib.util.spec_from_file_location('tool',Path(__file__).parents[1]/'local_apps_tool.py');tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool)
class ToolTest(unittest.TestCase):
 def test_roundtrip(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();source=p/'words.tsv';source.write_text('书\tbook\n');tool.import_words(p,source);self.assertEqual(tool.load_words(p),[('书','book',False)]);source.write_text('malformed');self.assertRaises(ValueError,tool.import_words,p,source);self.assertEqual(tool.load_words(p),[('书','book',False)])
 def test_notes_unicode_import_export(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();src=p/'original.txt';src.write_text('笔记\nUnicode 😀');tool.import_note(p,src);dest=p/'export';tool.export_notes(p,dest);self.assertEqual((dest/'1.txt').read_text(),src.read_text());self.assertRaises(FileExistsError,tool.export_notes,p,dest)
 def test_symlink_and_permissions(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp).resolve();src=p/'s';src.write_text('a\tb\n');(p/'words').symlink_to(p,target_is_directory=True);self.assertRaises(ValueError,tool.import_words,p,src)
 def test_limits(self):
  self.assertRaises(ValueError,tool.parse_tsv,b'a\t\xff\n');self.assertRaises(ValueError,tool.parse_tsv,b'a'*257+b'\tb\n');self.assertRaises(ValueError,tool.parse_tsv,b'a\tb\n'*1001)
if __name__=='__main__':unittest.main()

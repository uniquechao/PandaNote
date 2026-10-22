"""Exact owned-process lifecycle for the offline proof, not a reader dependency.
No PID discovery/files, adoption, process groups, pkill or killall. Keep Popen
handles until wait/reap; a child cannot have its PID reused while unreaped.
"""
import subprocess
class Children:
    def __init__(self):self.children=[]
    def spawn(self,argv,**kwargs):
        child=subprocess.Popen(argv,**kwargs);self.children.append(child);return child
    def stop(self,child,grace=.5):
        if not any(child is x for x in self.children):raise ValueError('unowned child')
        if not 0<grace<=2:raise ValueError('unbounded grace')
        if child.poll() is not None:return 'already_exited'
        child.terminate()
        try:child.wait(timeout=grace);return 'terminated'
        except subprocess.TimeoutExpired:
            child.kill();child.wait(timeout=grace);return 'killed'
    def close(self):
        result=[];failure=None
        for child in reversed(self.children):
            try:result.append(self.stop(child))
            except Exception as error:failure=error
        if failure:raise failure
        return result

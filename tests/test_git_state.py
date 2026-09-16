import subprocess
import shutil
import pytest
from briefing.state import State

@pytest.mark.skipif(not shutil.which('git'),reason='git required')
def test_state_only_commit_push_to_local_bare_remote(tmp_path,monkeypatch):
    repo=tmp_path/'repository'; remote=tmp_path/'remote.git'; repo.mkdir()
    def git(*args,cwd=repo): return subprocess.run(['git',*args],cwd=cwd,check=True,capture_output=True,text=True).stdout.strip()
    git('init','--bare',str(remote)); git('init','-b','main')
    git('config','user.name','Fixture'); git('config','user.email','fixture@example.com')
    (repo/'README.md').write_text('Test repository')
    git('add','README.md'); git('commit','-m','fixture'); git('remote','add','origin',str(remote)); git('push','-u','origin','main')
    monkeypatch.setattr('briefing.state.ROOT',repo)
    state=State(repo/'data/state.json',persist_git=True); state.reserve('daily:fixture')
    remote_state=git('--git-dir',str(remote),'show','main:data/state.json')
    assert 'sending' in remote_state
    assert git('show','--pretty=','--name-only','HEAD')=='data/state.json'
    (repo/'unexpected.txt').write_text('Should never be included'); git('add','unexpected.txt')
    with pytest.raises(ValueError,match='Unexpected staged'): state.finish('daily:fixture','smtp_accepted')

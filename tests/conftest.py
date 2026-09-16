import os
import tempfile
import shutil
from pathlib import Path
import pytest

TEST_DATA=Path(tempfile.mkdtemp(prefix='kindle-brief-tests-'))
os.environ['BRIEFING_DATA']=str(TEST_DATA)

@pytest.fixture(autouse=True)
def database():
    from briefing.core import init,db
    init()
    with db() as c:
        for table in ('articles','snapshots','editions','jobs','deliveries'): c.execute('DELETE FROM '+table)

def pytest_sessionfinish(session,exitstatus):
    shutil.rmtree(TEST_DATA)

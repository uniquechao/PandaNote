"""Native device protocol tests, unchanged reviewed offline execution gates."""
import datetime,json,shutil
from pathlib import Path
import run as common

def main():
    evidence=common.ROOT/'build'/('tls-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));evidence.mkdir(parents=True)
    try:
        binary=common.build(evidence,['tls.cpp','tests/tls_cases.cpp'],'tls')
        # Generate only synthetic protocol fixtures; do not read manager/private state.
        return common.execute(binary,evidence)
    except Exception as error: print('FAIL tls: '+str(error));return 1
    finally: (evidence/'commands.json').write_text(json.dumps(common.COMMANDS,indent=2)+'\n');print('evidence: '+str(evidence))
if __name__=='__main__':raise SystemExit(main())

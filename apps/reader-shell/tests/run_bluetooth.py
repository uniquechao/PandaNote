"""Native Bluetooth IPC and GUI; retained strict offline execution gates."""
import datetime,json
import run as common

def main():
 evidence=common.ROOT/'build'/('bluetooth-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'));evidence.mkdir(parents=True)
 try:
  binary=common.build(evidence,['bluetooth.cpp','tests/bluetooth_cases.cpp'],'bluetooth')
  common.build(evidence,['content.cpp','navigation.cpp','sync.cpp','shell.cpp','tests/shell_cases.cpp'],'shell')
  return common.execute(binary,evidence)
 except Exception as e:print('FAIL bluetooth: '+str(e));return 1
 finally:(evidence/'commands.json').write_text(json.dumps(common.COMMANDS,indent=2)+'\n');print('evidence: '+str(evidence))
if __name__=='__main__':raise SystemExit(main())

"""Task2 scoped navigation runner; retains the Task1 execution gates."""
import datetime,json
import run as common

def main():
    evidence=common.ROOT/'build'/('navigation-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    evidence.mkdir(parents=True)
    try:
        missing=[name for name in ('navigation.h','navigation.cpp','shell.h','shell.cpp') if not (common.ROOT/name).is_file()]
        if missing:
            print('FAIL navigation implementation missing: '+', '.join(missing));return 1
        provenance=json.loads((common.ROOT/'assets/font-provenance.json').read_text())
        for item in provenance['files']:
            if common.sha(common.ROOT/'assets'/item['file'])!=item['sha256']:
                raise RuntimeError('font provenance hash failed: '+item['file'])
        binary=common.build(evidence, ['localapps.cpp','tests/local_apps_cases.cpp'], 'navigation')
        # GUI harness must link before any offline execution, using the same ABI gates.
        common.build(evidence, ['content.cpp','navigation.cpp','sync.cpp','localapps.cpp','shell.cpp','tests/shell_cases.cpp'], 'shell')
        return common.execute(binary,evidence)
    except Exception as error:
        print('FAIL navigation: '+str(error));return 1
    finally:
        (evidence/'commands.json').write_text(json.dumps(common.COMMANDS,indent=2)+'\n')
        print('evidence: '+str(evidence))

if __name__ == "__main__": raise SystemExit(main())

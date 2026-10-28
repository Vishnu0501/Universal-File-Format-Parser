import sys
import os
from parser import parse, scan, RecordType


def run(path: str):
    if not os.path.exists(path):
        print(f"Error: File not found — {path}")
        sys.exit(1)

    with open(path, "rb") as f:
        data = f.read()

    filename = os.path.basename(path)
    size_kb = len(data) / 1024

    print(f"\n{'='*65}")
    print(f"  FILE   : {filename}")
    print(f"  PATH   : {path}")
    print(f"  SIZE   : {size_kb:.1f} KB")
    print(f"{'='*65}")

    print("\n[ PARSE RESULTS ]\n")
    count = {"data": 0, "error": 0, "warning": 0}

    for r in parse(data, filename=filename):
        if r.type == RecordType.DATA:
            count["data"] += 1
            meta = " | ".join(f"{k}={v}" for k, v in r.metadata.items())
            content = str(r.content)
            # preview = content[:2000] + "..." if len(content) > 2000 else content
            print(content)
            print(f"  [DATA #{count['data']}]")
            if meta:
                print(f"    meta    : {meta}")
            print(f"    content : {content}")
            print()

        elif r.type == RecordType.ERROR:
            count["error"] += 1
            print(f"  [ERROR #{count['error']}]")
            print(f"    format  : {r.format}")
            print(f"    offset  : {r.offset}")
            print(f"    reason  : {r.reason}")
            print()

        elif r.type == RecordType.WARNING:
            count["warning"] += 1
            print(f"  [WARNING #{count['warning']}]")
            print(f"    format   : {r.format}")
            print(f"    severity : {r.severity}")
            print(f"    reason   : {r.reason}")
            print()

    print(f"  Summary: {count['data']} data | {count['error']} errors | {count['warning']} warnings")

    print(f"\n[ SECURITY SCAN ]\n")
    threats = list(scan(data, filename=filename))
    if not threats:
        print("  Clean — no threats detected.\n")
    else:
        for r in threats:
            print(f"  [{r.severity}] {r.reason}")
            if r.metadata:
                print(f"    details: {r.metadata}")
        print()

    print("="*65)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python run_file.py <path_to_file>")
        print("Example: python run_file.py C:\\Users\\You\\Desktop\\report.pdf")
        sys.exit(1)

    for path in sys.argv[1:]:
        run(path)

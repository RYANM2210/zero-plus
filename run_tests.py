"""Run everything: unit tests, then both cross-checks.

    python run_tests.py [fuzz_count]
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TESTS = os.path.join(HERE, "tests")


def step(title, command):
    # Flush before handing the terminal to a child, or the headers land after
    # the output they are supposed to introduce.
    print("\n== %s ==" % title, flush=True)
    result = subprocess.call(command)
    if result != 0:
        print("FAILED: %s" % title, flush=True)
    return result


def main():
    count = sys.argv[1] if len(sys.argv) > 1 else "400"
    failures = 0
    failures += step("worked examples",
                     [sys.executable, os.path.join(TESTS, "test_cases.py")])
    failures += step("python vs javascript, worked examples",
                     [sys.executable, os.path.join(TESTS, "crosscheck.py")])
    subprocess.check_call([sys.executable, os.path.join(TESTS, "fuzz.py"), count],
                          stdout=subprocess.DEVNULL)
    failures += step("python vs javascript, %s random circuits" % count,
                     [sys.executable, os.path.join(TESTS, "crosscheck.py"), "fuzz"])
    print("\n%s" % ("all green" if failures == 0 else "%d step(s) failed" % failures), flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

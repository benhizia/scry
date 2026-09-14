"""Rapport JUnit XML, lu par la plupart des CI (Jenkins, GitLab, Azure...)."""

import os
import xml.etree.ElementTree as ET
from typing import Sequence


def write(results: Sequence, path: str, suite: str = "autotest") -> str:
    failures = sum(1 for r in results if r.status == "failed")
    errors = sum(1 for r in results if r.status == "error")
    root = ET.Element("testsuite", name=suite, tests=str(len(results)),
                      failures=str(failures), errors=str(errors),
                      time="%.3f" % sum(r.seconds for r in results))
    for r in results:
        case = ET.SubElement(root, "testcase", name=r.name, classname=r.scenario.module,
                             time="%.3f" % r.seconds)
        ET.SubElement(case, "properties").extend([
            ET.Element("property", name="cycles", value=str(r.cycles)),
            ET.Element("property", name="start_cycle", value=str(r.start_cycle)),
            ET.Element("property", name="slow_ticks", value=str(r.slow_ticks)),
        ])
        if r.status in ("failed", "error"):
            tag = "failure" if r.status == "failed" else "error"
            node = ET.SubElement(case, tag, message=r.message)
            node.text = "\n".join(list(r.checks_failed) + ([r.details] if r.details else []))
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path

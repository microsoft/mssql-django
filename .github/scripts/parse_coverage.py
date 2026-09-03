"""Parse Cobertura coverage.xml and export metrics to GITHUB_ENV."""
import xml.etree.ElementTree as ET
import os
import re
import uuid

root = ET.parse("coverage.xml").getroot()
covered = root.get("lines-covered", "0")
total = root.get("lines-valid", "0")
rate = float(root.get("line-rate", "0"))
pct = f"{rate * 100:.2f}%"

print(f"Overall: {pct} ({covered}/{total} lines)")

env_file = os.environ.get("GITHUB_ENV", "/dev/null")
with open(env_file, "a") as env:
    env.write(f"COVERAGE_PERCENTAGE={pct}\n")
    env.write(f"COVERED_LINES={covered}\n")
    env.write(f"TOTAL_LINES={total}\n")

# Regex to strip ADO agent workspace prefixes
agent_prefix_re = re.compile(
    r"^(/mnt/vss/_work/\d+/s/|/home/vsts/work/\d+/s/|[A-Z]:\\\\.*?\\\\s\\\\|\\./)(.*)$"
)

files = []
for cls in root.iter("class"):
    fname = cls.get("filename", cls.get("name", "unknown"))
    match = agent_prefix_re.match(fname)
    if match:
        fname = match.group(2)
    lr = float(cls.get("line-rate", "0"))
    lines_elem = cls.find("lines")
    line_count = len(lines_elem.findall("line")) if lines_elem is not None else 0
    files.append((fname, lr * 100, line_count))

files.sort(key=lambda x: x[1])
low_cov = "\n".join(
    f"- {f}: {p:.1f}%  ({l} lines)" for f, p, l in files[:10]
)
print(f"\nLowest coverage files:\n{low_cov}")

delim = f"DELIM_{uuid.uuid4().hex}"
with open(env_file, "a") as env:
    env.write(f"LOW_COVERAGE_FILES<<{delim}\n{low_cov}\n{delim}\n")

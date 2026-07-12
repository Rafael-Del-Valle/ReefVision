import { readFileSync } from "node:fs";

const lockfileUrl = new URL("../package-lock.json", import.meta.url);
const lockfile = JSON.parse(readFileSync(lockfileUrl, "utf8"));
const invalidResolvedEntries = [];
const visited = new Set();

function visit(node, path) {
  if (!node || typeof node !== "object" || visited.has(node)) {
    return;
  }
  visited.add(node);

  if (typeof node.resolved === "string") {
    try {
      const resolvedUrl = new URL(node.resolved);
      if (resolvedUrl.hostname !== "registry.npmjs.org") {
        invalidResolvedEntries.push({ path, resolved: node.resolved });
      }
    } catch {
      invalidResolvedEntries.push({ path, resolved: node.resolved });
    }
  }

  for (const [key, value] of Object.entries(node)) {
    visit(value, `${path}.${key}`);
  }
}

visit(lockfile, "package-lock");

if (invalidResolvedEntries.length > 0) {
  console.error("package-lock.json contains non-public registry URLs:");
  for (const entry of invalidResolvedEntries) {
    console.error(`- ${entry.path}: ${entry.resolved}`);
  }
  process.exit(1);
}

console.log("package-lock.json uses only registry.npmjs.org resolved URLs.");

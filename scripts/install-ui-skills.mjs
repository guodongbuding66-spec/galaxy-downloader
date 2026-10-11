import { spawnSync } from "node:child_process"
import process from "node:process"

const npx = process.platform === "win32" ? "npx.cmd" : "npx"
const commands = [
  ["skills", "add", "Leonxlnx/taste-skill"],
  ["impeccable", "install"],
  ["ui-skills"],
]

for (const args of commands) {
  const label = `npx ${args.join(" ")}`
  console.log(`\n[Galaxy UI] ${label}`)
  const result = spawnSync(npx, args, {
    cwd: process.cwd(),
    env: process.env,
    stdio: "inherit",
    shell: false,
  })
  if (result.error) {
    console.error(`[Galaxy UI] failed to launch ${label}: ${result.error.message}`)
    process.exit(1)
  }
  if (result.status !== 0) {
    console.error(`[Galaxy UI] ${label} exited with code ${result.status ?? "unknown"}`)
    process.exit(result.status ?? 1)
  }
}

console.log("\n[Galaxy UI] UI skill installation complete.")
console.log("[Galaxy UI] Use .agents/skills/galaxy-ui/SKILL.md as the project routing contract.")

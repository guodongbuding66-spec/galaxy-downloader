import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

function read(path: string): string {
  return readFileSync(resolve(process.cwd(), path), 'utf8')
}

describe('repository security baseline', () => {
  it('keeps CodeQL enabled for TypeScript/JavaScript and Python in primary CI', () => {
    const workflow = read('.github/workflows/ci.yml')

    expect(workflow).toContain('security-events: write')
    expect(workflow).toContain('javascript-typescript')
    expect(workflow).toContain('python')
    expect(workflow).toContain('security-extended,security-and-quality')
    expect(workflow).toContain('github/codeql-action/init@cdf488f595d80d6e07e03d4674febd5ab45fa938')
    expect(workflow).toContain('github/codeql-action/analyze@cdf488f595d80d6e07e03d4674febd5ab45fa938')
  })

  it('audits installed JavaScript and Python package ecosystems', () => {
    const workflow = read('.github/workflows/security-audit.yml')

    expect(workflow).toContain('pnpm audit --prod --audit-level=high')
    expect(workflow).toContain("pip-audit>=2.9,<3")
    expect(workflow).toContain('pnpm/setup@703c52620218391530e48b9e8870d5c0082e1b9b')
    expect(workflow).toContain('local-engine/requirements.txt')
    expect(workflow).toContain('container-backend/requirements.txt')
    expect(workflow).not.toContain('actions/dependency-review-action')
  })

  it('keeps automated update coverage for npm, pip and GitHub Actions', () => {
    const dependabot = read('.github/dependabot.yml')

    expect(dependabot.match(/package-ecosystem: npm/g)?.length).toBeGreaterThanOrEqual(2)
    expect(dependabot.match(/package-ecosystem: pip/g)?.length).toBeGreaterThanOrEqual(2)
    expect(dependabot).toContain('package-ecosystem: github-actions')
    expect(dependabot).toContain('open-pull-requests-limit')
  })

  it('uses current action runtimes in primary CI', () => {
    const workflow = read('.github/workflows/ci.yml')

    expect(workflow).toContain('actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0')
    expect(workflow).toContain('pnpm/setup@703c52620218391530e48b9e8870d5c0082e1b9b')
    expect(workflow).toContain('runtime: node@22')
    expect(workflow).not.toContain('actions/checkout@v4')
    expect(workflow).not.toContain('actions/setup-node@v4')
    expect(workflow).not.toContain('pnpm/action-setup@v4')
  })

  it('pins every external GitHub Action to an immutable commit SHA', () => {
    const workflowDir = resolve(process.cwd(), '.github/workflows')
    const workflowFiles = readdirSync(workflowDir).filter((file) => /\.ya?ml$/.test(file))

    for (const file of workflowFiles) {
      const workflow = read(`.github/workflows/${file}`)
      for (const match of workflow.matchAll(/^\s*uses:\s*([^\s#]+)(?:\s+#.*)?$/gm)) {
        const action = match[1]
        if (action.startsWith('./')) continue
        expect(action).toMatch(/^[^@\s]+@[0-9a-f]{40}$/)
      }
    }
  })

  it('pins secret-bearing PR Agent execution and limits it to trusted PR actors', () => {
    const workflow = read('.github/workflows/pr-agent.yml')

    expect(workflow).toContain('the-pr-agent/pr-agent@ab6ec54bfeb37933ddb74259338752e9272016c6')
    expect(workflow).not.toContain('the-pr-agent/pr-agent@main')
    expect(workflow).toContain('github.event.pull_request.author_association')
    expect(workflow).toContain('github.event.comment.author_association')
    expect(workflow).toContain('["OWNER","MEMBER","COLLABORATOR"]')
    expect(workflow).toContain('github.event.issue.pull_request')
  })

  it('documents security-sensitive ownership and reporting', () => {
    const codeowners = read('.github/CODEOWNERS')
    const security = read('SECURITY.md')

    expect(codeowners).toContain('/.github/workflows/')
    expect(codeowners).toContain('/src/app/api/proxy-image/')
    expect(codeowners).toContain('/local-engine/')
    expect(security).toContain('Reporting a vulnerability')
    expect(security).toContain('actual streamed body')
  })
})

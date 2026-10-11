import Link from "next/link"
import type { Locale } from "@/lib/i18n/config"
import type { Dictionary } from "@/lib/i18n/types"

interface FooterProps {
    locale: Locale
    dict: Dictionary
}

export function Footer({ locale, dict }: FooterProps) {
    const currentYear = new Date().getFullYear()

    return (
        <footer className="mt-auto border-t py-4">
            <div className="mx-auto flex max-w-[1380px] flex-col gap-2 px-3 text-xs leading-5 text-muted-foreground sm:px-4 md:px-5 lg:flex-row lg:items-center lg:justify-between">
                <p className="min-w-0 text-pretty">
                    {dict.page.copyrightYear.replace("{year}", String(currentYear))}
                    <span className="mx-1.5 text-border">·</span>
                    {dict.page.copyrightVideo}
                    <span className="mx-1.5 hidden text-border sm:inline">·</span>
                    <span className="hidden sm:inline">{dict.page.copyrightStorage}</span>
                </p>
                <nav className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1" aria-label={dict.common.trustAndPolicies}>
                    <Link className="rounded-sm underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40" href={`/${locale}/privacy`} prefetch={false}>
                        {dict.common.privacy}
                    </Link>
                    <Link className="rounded-sm underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40" href={`/${locale}/terms`} prefetch={false}>
                        {dict.common.terms}
                    </Link>
                    <Link className="rounded-sm underline-offset-4 hover:text-foreground hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/40" href={`/${locale}/contact`} prefetch={false}>
                        {dict.common.contact}
                    </Link>
                </nav>
            </div>
        </footer>
    )
}

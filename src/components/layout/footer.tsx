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
        <footer className="mt-auto border-t py-3">
            <div className="mx-auto flex max-w-[1380px] flex-col gap-1 px-3 text-[10px] leading-4 text-muted-foreground sm:px-4 md:px-5 lg:flex-row lg:items-center lg:justify-between">
                <p className="min-w-0">
                    {dict.page.copyrightYear.replace("{year}", String(currentYear))}
                    <span className="mx-1.5 text-border">·</span>
                    {dict.page.copyrightVideo}
                    <span className="mx-1.5 hidden text-border sm:inline">·</span>
                    <span className="hidden sm:inline">{dict.page.copyrightStorage}</span>
                </p>
                <nav className="flex shrink-0 flex-wrap items-center gap-x-2.5" aria-label={dict.common.trustAndPolicies}>
                    <Link className="underline-offset-4 hover:text-foreground hover:underline" href={`/${locale}/privacy`} prefetch={false}>
                        {dict.common.privacy}
                    </Link>
                    <Link className="underline-offset-4 hover:text-foreground hover:underline" href={`/${locale}/terms`} prefetch={false}>
                        {dict.common.terms}
                    </Link>
                    <Link className="underline-offset-4 hover:text-foreground hover:underline" href={`/${locale}/contact`} prefetch={false}>
                        {dict.common.contact}
                    </Link>
                </nav>
            </div>
        </footer>
    )
}
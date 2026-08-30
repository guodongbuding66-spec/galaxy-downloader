'use client'

import { useState, useEffect, useRef } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import { Button } from '@/components/ui/button'
import { Globe, ChevronDown, Check } from 'lucide-react'
import type { Locale } from '@/lib/i18n/config'
import { useAppLocale, useDictionary } from '@/i18n/client'
import { getLocaleLabel, SUPPORTED_LOCALES } from '@/lib/i18n/locale-meta'
import { LOCALE_COOKIE_NAME, LOCALE_COOKIE_MAX_AGE } from '@/lib/constants'
import { cn } from '@/lib/utils'

interface LanguageSwitcherProps {
    compact?: boolean
    defaultOpen?: boolean
    fullWidth?: boolean
    iconOnly?: boolean
}

function setLocaleCookie(locale: Locale) {
    const secureAttr = window.location.protocol === 'https:' ? '; Secure' : ''
    document.cookie = `${LOCALE_COOKIE_NAME}=${locale}; path=/; max-age=${LOCALE_COOKIE_MAX_AGE}; SameSite=Lax${secureAttr}`
}

export function LanguageSwitcher({
    compact = false,
    defaultOpen = false,
    fullWidth = false,
    iconOnly = false,
}: LanguageSwitcherProps) {
    const dict = useDictionary()
    const currentLocale = useAppLocale()
    const [isOpen, setIsOpen] = useState(defaultOpen)
    const pathname = usePathname()
    const router = useRouter()
    const dropdownRef = useRef<HTMLDivElement>(null)

    const safePathname = pathname || `/${currentLocale}`
    const pathWithoutLocale = safePathname.replace(`/${currentLocale}`, '') || '/'

    const handleLanguageChange = (locale: Locale) => {
        if (locale === currentLocale) {
            setIsOpen(false)
            return
        }

        const newPath = `/${locale}${pathWithoutLocale}`
        setLocaleCookie(locale)
        router.push(newPath)
        setIsOpen(false)
    }

    useEffect(() => {
        function handleClickOutside(event: MouseEvent) {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsOpen(false)
            }
        }

        if (isOpen) {
            document.addEventListener('mousedown', handleClickOutside)
            return () => document.removeEventListener('mousedown', handleClickOutside)
        }
    }, [isOpen])

    useEffect(() => {
        function handleEscapeKey(event: KeyboardEvent) {
            if (event.key === 'Escape') {
                setIsOpen(false)
            }
        }

        if (isOpen) {
            document.addEventListener('keydown', handleEscapeKey)
            return () => document.removeEventListener('keydown', handleEscapeKey)
        }
    }, [isOpen])

    return (
        <div className="relative" ref={dropdownRef}>
            <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsOpen((open) => !open)}
                className={cn(
                    'flex min-h-10 items-center gap-2 text-sm',
                    compact && 'max-w-[8rem] gap-1.5 px-2.5',
                    iconOnly && 'h-10 w-10 p-0',
                    fullWidth && 'w-full justify-between'
                )}
                aria-label={iconOnly ? dict.page.switchLanguageLabel : getLocaleLabel(currentLocale)}
                aria-haspopup="menu"
                aria-expanded={isOpen}
            >
                <Globe className="h-4 w-4" aria-hidden="true" />
                {iconOnly ? (
                    <span className="sr-only">{dict.page.switchLanguageLabel}</span>
                ) : compact ? (
                    <span className="max-w-[5.5rem] truncate">{getLocaleLabel(currentLocale)}</span>
                ) : (
                    <>
                        <span>{getLocaleLabel(currentLocale)}</span>
                        <ChevronDown className={`h-4 w-4 transition-transform ${isOpen ? 'rotate-180' : ''}`} aria-hidden="true" />
                    </>
                )}
            </Button>

            {isOpen && (
                <div
                    className="absolute end-0 top-full z-50 mt-1 w-44 overflow-hidden rounded-xl border border-border bg-background p-1 shadow-lg"
                    role="menu"
                    aria-label={dict.page.switchLanguageLabel}
                >
                    {SUPPORTED_LOCALES.map((locale) => {
                        const selected = locale === currentLocale
                        return (
                            <button
                                key={locale}
                                type="button"
                                role="menuitemradio"
                                aria-checked={selected}
                                onClick={() => handleLanguageChange(locale)}
                                className="flex min-h-10 w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-start text-sm transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                                <span>{getLocaleLabel(locale)}</span>
                                {selected && (
                                    <Check className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
                                )}
                            </button>
                        )
                    })}
                </div>
            )}
        </div>
    )
}

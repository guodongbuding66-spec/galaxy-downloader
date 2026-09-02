from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "src/components/downloader/BatchWorkbench.tsx"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "  useEffect(() => {\n    setSubmissionResult(null)\n    setSubmissionError('')\n  }, [format, input])\n\n",
        "",
        "remove synchronous reset effect",
    )

    text = replace_once(
        text,
        "      setInput(text)\n      setFileName('')\n      setInputError('')\n    } catch (error) {",
        "      setInput(text)\n      setFileName('')\n      setInputError('')\n      setSubmissionResult(null)\n      setSubmissionError('')\n    } catch (error) {",
        "paste reset",
    )

    text = replace_once(
        text,
        "      setInput(text)\n      setFileName(file.name)\n      setInputError('')\n      toast.success",
        "      setInput(text)\n      setFileName(file.name)\n      setInputError('')\n      setSubmissionResult(null)\n      setSubmissionError('')\n      toast.success",
        "file reset",
    )

    text = replace_once(
        text,
        "              onChange={(event) => {\n                setInput(event.target.value)\n                setFileName('')\n                setInputError('')\n              }}",
        "              onChange={(event) => {\n                setInput(event.target.value)\n                setFileName('')\n                setInputError('')\n                setSubmissionResult(null)\n                setSubmissionError('')\n              }}",
        "textarea reset",
    )

    text = replace_once(
        text,
        "              <Select value={format} onValueChange={(value) => setFormat(value as BatchWorkbenchFormat)}>",
        "              <Select\n                value={format}\n                onValueChange={(value) => {\n                  setFormat(value as BatchWorkbenchFormat)\n                  setSubmissionResult(null)\n                  setSubmissionError('')\n                }}\n              >",
        "format reset",
    )

    text = replace_once(
        text,
        "                setInput('')\n                setFileName('')\n                setInputError('')\n              }}",
        "                setInput('')\n                setFileName('')\n                setInputError('')\n                setSubmissionResult(null)\n                setSubmissionError('')\n              }}",
        "clear reset",
    )

    TARGET.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()

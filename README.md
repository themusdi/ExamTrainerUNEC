<div align="center">

# 🎓 ExamTrainer

**A lightweight desktop exam simulator for UNEC students.**
Load your question-bank PDF, pick any set of question numbers, and sit a randomised exam of *N* questions — with images, instant feedback and a full review.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)
![GUI](https://img.shields.io/badge/GUI-Tkinter-informational)

</div>

> **UNEC-specific.** ExamTrainer is built around the test-bank PDF format used at UNEC (Azerbaijan State University of Economics): numbered questions, with every answer variant marked `•` (wrong) or `√` (correct).
> This is an independent student project and is **not affiliated with or endorsed by UNEC**.

---

## Table of contents

- [Features](#-features)
- [Quick start (Windows `.exe`)](#-quick-start-windows-exe)
- [Run from source](#-run-from-source)
- [How to use](#-how-to-use)
- [Supported PDF format](#-supported-pdf-format)
- [Building the Windows executable](#-building-the-windows-executable)
- [Project structure](#-project-structure)
- [Notes & limitations](#-notes--limitations)
- [Qısa izah (Azərbaycan dilində)](#-qısa-izah-azərbaycan-dilində)
- [Author](#-author)
- [License](#-license)

## ✨ Features

| | |
|---|---|
| 📄 **Any bank, one file** | Choose your question PDF at startup — no conversion step. |
| 🔢 **Flexible selection** | `7` · `5-61` · `1,5-61,69,73-152` — single numbers, ranges, or any mix. Empty means *all*. |
| 🎲 **Random N questions** | Enter a count (e.g. `30` or `50`); questions are drawn at random from your selection. |
| 🖼️ **Image-aware** | Pictures in questions or variants (formulas, graphs, diagrams) are cropped from the PDF and shown as-is. Nothing is OCR'd or guessed. |
| ✅ **Practice mode** | Optional instant right/wrong feedback after each answer. |
| 🔀 **Shuffle variants** | Optionally randomise the order of A–E. |
| 📊 **Detailed results** | Score, percentage, and a per-question review: correct answer in green, your wrong pick in red. |
| 🔁 **Retry mistakes** | Re-take only the questions you got wrong or skipped. |
| ⌨️ **Keyboard shortcuts** | `A`–`E` select an answer, `←` / `→` move between questions. |
| ⚡ **Fast** | A 166-page, 700-question PDF is parsed in seconds; images are rendered lazily, only for the questions you actually see. |

## 🚀 Quick start (Windows `.exe`)

The Windows build is a **single `ExamTrainer.exe`**. You do **not** need to install Python, `pdfplumber`, `pypdfium2`, `Pillow` or any other package.

1. Download `ExamTrainer.exe` (see [Building the Windows executable](#-building-the-windows-executable) if you need to produce it yourself).
2. Double-click it.
3. Select your question PDF, enter the question numbers and count, and press **Start exam**.

> Windows SmartScreen may warn about an unsigned executable. Choose **More info → Run anyway** if you built it yourself or trust the source.

## 🐍 Run from source

Requires **Python 3.9+**. Tkinter ships with Python on Windows and macOS; on Debian/Ubuntu install it with `sudo apt install python3-tk`.

```bash
git clone https://github.com/themusdi/ExamTrainer.git
cd ExamTrainer
pip install -r requirements.txt
python exam_app.py
```

## 📝 How to use

1. **PDF file** — click **Browse…** and choose your question bank. The app reports how many questions it found.
2. **Which questions?** — type the numbers you want to practise, e.g. `1,5-61,69,73-152`. The pool size is shown live.
3. **How many questions?** — enter `30`, `50`, … (or click **All from the pool**). *N* random questions are picked from the pool.
4. *(Optional)* tick **Practice mode** and/or **Shuffle the variants**.
5. Press **Start exam**, answer, then **Finish exam** to see your score and review.

## 📑 Supported PDF format

The parser expects the exact structure of the UNEC test-bank export:

```text
12. Text of the question ...
    •  wrong variant
    •  wrong variant
    √  the one correct variant
    •  wrong variant
```

- Questions are numbered `1.`, `2.`, `3.` …
- Each variant starts with `•` (wrong) or `√` (correct); exactly one `√` per question.
- A question or a variant may contain an image.
- The file is **not validated** — it is assumed to follow this format. Numbers requested but absent from the file are reported and skipped.

## 🛠️ Building the Windows executable

> This produces a **Windows `.exe`**. It does not run on macOS, Linux, Android or iOS — those platforms need their own build or a web version.

### Option A — GitHub Actions (no local Python needed)

1. Create a GitHub repository and upload **all files and folders** of this project.
2. Keep the workflow file at exactly this path:
   `.github/workflows/build-windows.yml`
3. Open the repository's **Actions** tab.
4. Select **Build Windows EXE** and run it (or simply push to `main` / `master`).
5. When the run finishes, open it and download the **`ExamTrainer-Windows`** artifact.
6. Extract the ZIP — it contains `ExamTrainer.exe`.

### Option B — Build locally on Windows

1. Install **Python 3.12** once.
2. Double-click **`build.bat`** — it installs the build dependencies automatically.
3. Your executable will be at `dist\ExamTrainer.exe`.

Under the hood this is simply:

```bash
pip install -r requirements.txt pyinstaller
pyinstaller --onefile --windowed --name ExamTrainer exam_app.py
```

## 📂 Project structure

```text
ExamTrainer/
├── exam_app.py                      # the whole application (parser + GUI)
├── requirements.txt                 # pdfplumber, pypdfium2, Pillow
├── build.bat                        # one-click local Windows build
├── .github/
│   └── workflows/
│       └── build-windows.yml        # CI: builds ExamTrainer.exe
├── LICENSE                          # MIT
└── README.md
```

## ⚠️ Notes & limitations

- **Question banks are not included.** Test-bank PDFs may be copyrighted — bring your own file and do not commit it to the repository (`*.pdf` is git-ignored).
- The app asks for the PDF every time it starts.
- Questions that depend on a variant's *position* (e.g. "all of the above") can break if **Shuffle the variants** is on — it is off by default.
- Scanned (image-only) PDFs without a text layer are not supported.
- Unsigned executables may trigger Windows SmartScreen warnings.

## 🇦🇿 Qısa izah (Azərbaycan dilində)

**ExamTrainer** — UNEC tələbələri üçün hazırlanmış sadə imtahan məşq proqramıdır.

1. Test bazası **PDF** faylını seçirsən (sual nömrələnməlidir; `•` — səhv, `√` — düzgün variant).
2. Hansı sualların olacağını yazırsan: `7`, `5-61` və ya qarışıq `1,5-61,69,73-152`.
3. Neçə sual istədiyini yazırsan (məs. `30` və ya `50`) — suallar həmin aralıqdan **təsadüfi** seçilir.
4. İmtahanı həll edib nəticəni və səhvlərini görürsən; istəsən yalnız səhv suallarla yenidən başlaya bilərsən.

Şəkilli suallar PDF-dən kəsilib olduğu kimi göstərilir. Windows üçün hazır **`ExamTrainer.exe`** Python quraşdırmadan işləyir (bax: [Building the Windows executable](#-building-the-windows-executable)).

> Layihə UNEC ilə rəsmi əlaqəli deyil. Test bazası PDF-ləri repoya əlavə edilməməlidir.

## 👤 Author

**themusdi** · [GitHub](https://github.com/themusdi) · [Instagram](https://instagram.com/the.musdi)

Issues and pull requests are welcome. If ExamTrainer helps you, a ⭐ on the repository is appreciated.

## 📄 License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for the full text.

```text
MIT License

Copyright (c) 2026 themusdi

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DocsRoot = Join-Path $Root "docs\jiangsu"
$MajorPdfDir = Join-Path $DocsRoot "source\2.江苏省高等教育自学考试面向社会开考专业考试计划（2024年版）"
$ProcessedDir = Join-Path $DocsRoot "source\processed"
$TextbookPdfDir = Join-Path $DocsRoot "source\textbooks"
$SyllabusPdfDir = Join-Path $DocsRoot "source\syllabus"
$PastPaperPdfDir = Join-Path $DocsRoot "source\past-papers"

$NameSlugMap = @{
  "机械制造及自动化" = "mechanical-manufacturing-and-automation"
  "机电一体化技术" = "mechatronics-technology"
  "中药学" = "chinese-materia-medica"
  "工商企业管理" = "business-enterprise-management"
  "市场营销" = "marketing"
  "电子商务" = "e-commerce"
  "学前教育" = "preschool-education"
  "小学教育" = "primary-education"
  "心理健康教育" = "mental-health-education"
  "人力资源管理" = "human-resource-management"
  "行政管理" = "administrative-management"
  "金融学" = "finance"
  "国际经济与贸易" = "international-economics-and-trade"
  "法学" = "law"
  "汉语言文学" = "chinese-language-literature"
  "秘书学" = "secretarial-science"
  "英语" = "english"
  "商务英语" = "business-english"
  "新闻学" = "journalism"
  "广告学" = "advertising"
  "机械设计制造及其自动化" = "mechanical-design-manufacturing-and-automation"
  "汽车服务工程" = "automotive-service-engineering"
  "通信工程" = "communication-engineering"
  "计算机科学与技术" = "computer-science-and-technology"
  "网络工程" = "network-engineering"
  "物联网工程" = "internet-of-things-engineering"
  "土木工程" = "civil-engineering"
  "化学工程与工艺" = "chemical-engineering-and-technology"
  "环境工程" = "environmental-engineering"
  "食品科学与工程" = "food-science-and-engineering"
  "消防工程" = "fire-protection-engineering"
  "动物医学" = "animal-medicine"
  "园林" = "landscape-architecture"
  "药学" = "pharmacy"
  "护理学" = "nursing"
  "信息管理与信息系统" = "information-management-and-information-systems"
  "工程管理" = "engineering-management"
  "工商管理" = "business-administration"
  "会计学" = "accounting"
  "审计学" = "auditing"
  "农林经济管理" = "agricultural-and-forestry-economic-management"
  "物流管理" = "logistics-management"
  "工业工程" = "industrial-engineering"
  "旅游管理" = "tourism-management"
  "视觉传达设计" = "visual-communication-design"
  "环境设计" = "environmental-design"
  "数字媒体艺术" = "digital-media-art"
}

function Resolve-Tool {
  param([string]$Name)

  $command = Get-Command $Name -ErrorAction SilentlyContinue
  if ($command) {
    return $command.Source
  }

  $candidateRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
  if (Test-Path -LiteralPath $candidateRoot) {
    $candidate = Get-ChildItem -LiteralPath $candidateRoot -Recurse -Filter "$Name.exe" -ErrorAction SilentlyContinue |
      Select-Object -First 1
    if ($candidate) {
      return $candidate.FullName
    }
  }

  throw "Cannot find $Name. Install Poppler first."
}

function Write-Utf8File {
  param(
    [string]$Path,
    [string]$Content
  )

  $dir = Split-Path -Parent $Path
  if ($dir) {
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
  }
  [System.IO.File]::WriteAllText($Path, $Content, $Utf8NoBom)
}

function Get-RelativePath {
  param([string]$Path)
  return $Path.Replace($Root + "\", "")
}

function Escape-Html {
  param([string]$Value)
  return [System.Net.WebUtility]::HtmlEncode($Value)
}

function Get-SafeSlug {
  param([string]$Value)

  $slug = $Value.ToLowerInvariant()
  $slug = $slug -replace "[^a-z0-9]+", "-"
  $slug = $slug.Trim("-")
  if ([string]::IsNullOrWhiteSpace($slug)) {
    return "document"
  }
  return $slug
}

function Invoke-PdfRawConversion {
  param(
    [System.IO.FileInfo]$Pdf,
    [string]$OutputPrefix,
    [string]$TextOutput,
    [string]$PdfToHtml,
    [string]$PdfToText
  )

  $xmlOutput = "$OutputPrefix.xml"
  if ($Force) {
    foreach ($path in @($xmlOutput, $TextOutput)) {
      if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
      }
    }
  }

  if (-not (Test-Path -LiteralPath $xmlOutput)) {
    & $PdfToHtml -xml -i -noframes $Pdf.FullName $OutputPrefix | Out-Null
  }

  if (-not (Test-Path -LiteralPath $TextOutput)) {
    & $PdfToText -layout $Pdf.FullName $TextOutput
  }

  return @{
    RawXml = $xmlOutput
    RawTxt = $TextOutput
  }
}

function New-NormalizedHtml {
  param(
    [hashtable]$Meta,
    [string]$RawText
  )

  $title = Escape-Html $Meta.Title
  $sourcePdf = Escape-Html $Meta.SourcePdf
  $docType = Escape-Html $Meta.Type
  $code = Escape-Html $Meta.Code
  $name = Escape-Html $Meta.Name
  $level = Escape-Html $Meta.Level
  $generatedAt = Escape-Html $Meta.GeneratedAt
  $pages = $RawText -split "`f"
  $sections = New-Object System.Text.StringBuilder
  $pageNumber = 1

  foreach ($page in $pages) {
    $body = ($page -replace "`r", "").Trim()
    if ([string]::IsNullOrWhiteSpace($body)) {
      $pageNumber += 1
      continue
    }

    $escapedBody = Escape-Html $body
    [void]$sections.AppendLine("    <section data-section=""raw-page"" data-source-page=""$pageNumber"">")
    [void]$sections.AppendLine("      <h2>第 $pageNumber 页</h2>")
    [void]$sections.AppendLine("      <pre>$escapedBody</pre>")
    [void]$sections.AppendLine("    </section>")
    $pageNumber += 1
  }

  return @"
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>$title</title>
</head>
<body>
  <article data-document-type="$docType" data-source-pdf="$sourcePdf" data-generated-at="$generatedAt">
    <header>
      <h1>$title</h1>
      <dl>
        <dt>文档类型</dt>
        <dd>$docType</dd>
        <dt>专业代码</dt>
        <dd>$code</dd>
        <dt>专业名称</dt>
        <dd>$name</dd>
        <dt>层次</dt>
        <dd>$level</dd>
      </dl>
    </header>
$sections
  </article>
</body>
</html>
"@
}

function New-ExtractedMarkdown {
  param(
    [hashtable]$Meta,
    [string]$RawText,
    [string]$RawXmlRel,
    [string]$RawTxtRel,
    [string]$NormalizedHtmlRel
  )

  $text = (($RawText -replace "`r", "").Trim() -split "`n" | ForEach-Object { "    $_" }) -join "`n"
  return @"
# $($Meta.Title)

| 字段 | 内容 |
| --- | --- |
| 文档类型 | $($Meta.Type) |
| 源 PDF | $($Meta.SourcePdf) |
| 专业代码 | $($Meta.Code) |
| 专业名称 | $($Meta.Name) |
| 层次 | $($Meta.Level) |
| 数据状态 | 机器抽取草稿，待人工校对 |

## 转换产物

- Raw XML：$RawXmlRel
- Raw TXT：$RawTxtRel
- 规范化 HTML：$NormalizedHtmlRel

## 机器抽取文本

$text
"@
}

function New-PipelineNotes {
  param(
    [hashtable]$Meta,
    [string]$RawXmlRel,
    [string]$RawTxtRel,
    [string]$NormalizedHtmlRel,
    [string]$ExtractedMarkdownRel
  )

  return @"
# PDF 转换记录

| 字段 | 内容 |
| --- | --- |
| 源 PDF | $($Meta.SourcePdf) |
| 转换日期 | $($Meta.GeneratedAt) |
| 转换工具 | Poppler pdftohtml -xml -i -noframes；pdftotext -layout |
| 原始 XML | $RawXmlRel |
| 原始 TXT | $RawTxtRel |
| 规范化 HTML | $NormalizedHtmlRel |
| Markdown 草稿 | $ExtractedMarkdownRel |
| 数据状态 | 机器初稿，待人工校对 |

## 自动抽取问题

- [ ] 表格列是否错位：
- [ ] 页眉页脚是否混入正文：
- [ ] 课程代码是否缺失：
- [ ] 专业代码、专业名称、层次是否与官方 PDF 一致：

## 人工修正记录

| 位置 | 修改 | 原因 | 校对人/日期 |
| --- | --- | --- | --- |
"@
}

function Write-MajorStub {
  param(
    [hashtable]$Meta,
    [string]$MajorDir,
    [string]$RawXmlRel,
    [string]$RawTxtRel,
    [string]$NormalizedHtmlRel,
    [string]$ExtractedMarkdownRel
  )

  $indexPath = Join-Path $MajorDir "index.md"
  if (-not (Test-Path -LiteralPath $indexPath)) {
    $content = @"
# $($Meta.Name)（$($Meta.Level)）

| 字段 | 内容 |
| --- | --- |
| 省份 | 江苏 |
| 专业代码 | $($Meta.Code) |
| 专业名称 | $($Meta.Name) |
| 层次 | $($Meta.Level) |
| 数据状态 | PDF 已完成机器抽取，待人工校对 |

## 处理产物

- Raw XML：$RawXmlRel
- Raw TXT：$RawTxtRel
- 规范化 HTML：$NormalizedHtmlRel
- Markdown 草稿：$ExtractedMarkdownRel

## 待校对

- 专业基本信息。
- 课程清单与学分。
- 实践与毕业环节。
- 主考学校与教材来源。
"@
    Write-Utf8File $indexPath $content
  }

  $sourcesPath = Join-Path $MajorDir "sources.md"
  if (-not (Test-Path -LiteralPath $sourcesPath)) {
    $content = @"
# $($Meta.Name)（$($Meta.Level)）资料源清单

> 适用页面：[ $($Meta.Name)（$($Meta.Level)）](./index.md)

## 官方来源

| 来源 | 本地文件 |
| --- | --- |
| 专业考试计划 PDF | $($Meta.SourcePdf) |
| Raw XML | $RawXmlRel |
| Raw TXT | $RawTxtRel |
| 规范化 HTML | $NormalizedHtmlRel |
| Markdown 草稿 | $ExtractedMarkdownRel |

## 待补全

- 主考学校来源。
- 教材与考试大纲来源。
- 真题线索和版权审核。
"@
    Write-Utf8File $sourcesPath $content
  }
}

function Process-Document {
  param(
    [System.IO.FileInfo]$Pdf,
    [string]$OutDir,
    [string]$PrefixName,
    [hashtable]$Meta,
    [string]$PdfToHtml,
    [string]$PdfToText
  )

  New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
  $prefix = Join-Path $OutDir $PrefixName
  $textOutput = "$prefix.txt"
  $raw = Invoke-PdfRawConversion -Pdf $Pdf -OutputPrefix $prefix -TextOutput $textOutput -PdfToHtml $PdfToHtml -PdfToText $PdfToText
  $rawText = Get-Content -Raw -LiteralPath $raw.RawTxt

  $normalizedPath = Join-Path $OutDir ($PrefixName -replace "\.raw$", ".normalized.html")
  $extractedPath = Join-Path $OutDir ($PrefixName -replace "\.raw$", ".extracted.md")
  $notesPath = Join-Path $OutDir ($PrefixName -replace "\.raw$", ".pipeline-notes.md")

  Write-Utf8File $normalizedPath (New-NormalizedHtml -Meta $Meta -RawText $rawText)

  $rawXmlRel = Get-RelativePath $raw.RawXml
  $rawTxtRel = Get-RelativePath $raw.RawTxt
  $normalizedRel = Get-RelativePath $normalizedPath
  $extractedRel = Get-RelativePath $extractedPath

  Write-Utf8File $extractedPath (New-ExtractedMarkdown -Meta $Meta -RawText $rawText -RawXmlRel $rawXmlRel -RawTxtRel $rawTxtRel -NormalizedHtmlRel $normalizedRel)
  Write-Utf8File $notesPath (New-PipelineNotes -Meta $Meta -RawXmlRel $rawXmlRel -RawTxtRel $rawTxtRel -NormalizedHtmlRel $normalizedRel -ExtractedMarkdownRel $extractedRel)

  return @{
    RawXml = $raw.RawXml
    RawTxt = $raw.RawTxt
    NormalizedHtml = $normalizedPath
    ExtractedMarkdown = $extractedPath
    PipelineNotes = $notesPath
  }
}

$PdfToHtml = Resolve-Tool "pdftohtml"
$PdfToText = Resolve-Tool "pdftotext"
$GeneratedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"
$Manifest = New-Object System.Collections.Generic.List[object]
$MajorRows = New-Object System.Collections.Generic.List[object]

$majorPdfs = Get-ChildItem -LiteralPath $MajorPdfDir -Filter "*.pdf" -File | Sort-Object Name
foreach ($pdf in $majorPdfs) {
  $fileMatch = [regex]::Match($pdf.Name, "^(\d+)\.(.+?)专业（(.+?)）考试计划\.pdf$")
  if (-not $fileMatch.Success) {
    Write-Warning "Cannot parse major PDF filename: $($pdf.Name)"
    continue
  }

  $sequence = $fileMatch.Groups[1].Value
  $majorName = $fileMatch.Groups[2].Value
  $level = $fileMatch.Groups[3].Value
  $probeText = & $PdfToText -layout $pdf.FullName -
  $codeMatch = [regex]::Match(($probeText -join "`n"), "专业代码[：:]\s*([0-9A-Z]+)")
  $code = if ($codeMatch.Success) { $codeMatch.Groups[1].Value } else { "unknown-$sequence" }
  $slug = if ($NameSlugMap.ContainsKey($majorName)) { $NameSlugMap[$majorName] } else { "major-$sequence" }
  $majorDirName = "$code-$slug"
  $majorDir = Join-Path $DocsRoot "majors\$majorDirName"
  $outDir = Join-Path $majorDir "sources"
  $sourcePdfRel = Get-RelativePath $pdf.FullName
  $title = "$majorName（$level）"
  $meta = @{
    Type = "major-plan"
    SourcePdf = $sourcePdfRel
    Code = $code
    Name = $majorName
    Level = $level
    Title = $title
    GeneratedAt = $GeneratedAt
  }

  Write-Host "Processing major $sequence $title -> $majorDirName"
  $outputs = Process-Document -Pdf $pdf -OutDir $outDir -PrefixName "plan.raw" -Meta $meta -PdfToHtml $PdfToHtml -PdfToText $PdfToText

  $rawXmlRel = Get-RelativePath $outputs.RawXml
  $rawTxtRel = Get-RelativePath $outputs.RawTxt
  $normalizedRel = Get-RelativePath $outputs.NormalizedHtml
  $extractedRel = Get-RelativePath $outputs.ExtractedMarkdown
  Write-MajorStub -Meta $meta -MajorDir $majorDir -RawXmlRel $rawXmlRel -RawTxtRel $rawTxtRel -NormalizedHtmlRel $normalizedRel -ExtractedMarkdownRel $extractedRel

  $Manifest.Add([pscustomobject]@{
    type = "major-plan"
    title = $title
    code = $code
    source_pdf = $sourcePdfRel
    output_dir = Get-RelativePath $outDir
    raw_xml = $rawXmlRel
    raw_txt = $rawTxtRel
    normalized_html = $normalizedRel
    extracted_md = $extractedRel
  })
  $MajorRows.Add([pscustomobject]@{
    sequence = $sequence
    code = $code
    name = $majorName
    level = $level
    dir = Get-RelativePath $majorDir
  })
}

$sharedPdfs = Get-ChildItem -LiteralPath (Join-Path $DocsRoot "source") -Filter "*.pdf" -File |
  Where-Object { $_.FullName -notlike "$MajorPdfDir*" }
$textbookPdfDir = $TextbookPdfDir
if (Test-Path -LiteralPath $textbookPdfDir) {
  $sharedPdfs += Get-ChildItem -LiteralPath $textbookPdfDir -Filter "*.pdf" -File
}
$syllabusPdfDir = $SyllabusPdfDir
if (Test-Path -LiteralPath $syllabusPdfDir) {
  $sharedPdfs += Get-ChildItem -LiteralPath $syllabusPdfDir -Filter "*.pdf" -File
}
$pastPaperPdfDir = $PastPaperPdfDir
if (Test-Path -LiteralPath $pastPaperPdfDir) {
  $sharedPdfs += Get-ChildItem -LiteralPath $pastPaperPdfDir -Filter "*.pdf" -File -Recurse
}

foreach ($pdf in ($sharedPdfs | Sort-Object FullName)) {
  $stemSlug = Get-SafeSlug $pdf.BaseName
  $category = if ($pdf.FullName -like "$TextbookPdfDir*") {
    "textbooks"
  } elseif ($pdf.FullName -like "$SyllabusPdfDir*") {
    "syllabus"
  } elseif ($pdf.FullName -like "$PastPaperPdfDir*") {
    "past-papers"
  } else {
    "documents"
  }
  $outDir = if ($category -eq "past-papers") {
    $relativePastPaper = $pdf.FullName.Substring($PastPaperPdfDir.Length).TrimStart("\", "/")
    $relativeStem = [System.IO.Path]::Combine(
      (Split-Path -Parent $relativePastPaper),
      [System.IO.Path]::GetFileNameWithoutExtension($relativePastPaper)
    )
    $relativeSlug = (($relativeStem -split "[\\/]" | ForEach-Object { Get-SafeSlug $_ }) -join "\")
    Join-Path $ProcessedDir "$category\$relativeSlug"
  } else {
    Join-Path $ProcessedDir "$category\$stemSlug"
  }
  $sourcePdfRel = Get-RelativePath $pdf.FullName
  $meta = @{
    Type = $category
    SourcePdf = $sourcePdfRel
    Code = ""
    Name = $pdf.BaseName
    Level = ""
    Title = $pdf.BaseName
    GeneratedAt = $GeneratedAt
  }

  Write-Host "Processing shared PDF $($pdf.Name) -> $category/$stemSlug"
  $outputs = Process-Document -Pdf $pdf -OutDir $outDir -PrefixName "document.raw" -Meta $meta -PdfToHtml $PdfToHtml -PdfToText $PdfToText

  $Manifest.Add([pscustomobject]@{
    type = $category
    title = $pdf.BaseName
    code = ""
    source_pdf = $sourcePdfRel
    output_dir = Get-RelativePath $outDir
    raw_xml = Get-RelativePath $outputs.RawXml
    raw_txt = Get-RelativePath $outputs.RawTxt
    normalized_html = Get-RelativePath $outputs.NormalizedHtml
    extracted_md = Get-RelativePath $outputs.ExtractedMarkdown
  })
}

$manifestCsv = Join-Path $DocsRoot "source\pdf-processing-manifest.csv"
$Manifest | Export-Csv -NoTypeInformation -Encoding UTF8 -Path $manifestCsv

$majorIndex = Join-Path $DocsRoot "majors\index.md"
$majorLines = New-Object System.Text.StringBuilder
[void]$majorLines.AppendLine("# 江苏自考专业索引")
[void]$majorLines.AppendLine("")
[void]$majorLines.AppendLine("| 序号 | 专业代码 | 专业名称 | 层次 | 页面 |")
[void]$majorLines.AppendLine("| ---: | --- | --- | --- | --- |")
foreach ($row in ($MajorRows | Sort-Object sequence)) {
  $dirName = Split-Path -Leaf $row.dir
  [void]$majorLines.AppendLine("| $($row.sequence) | $($row.code) | $($row.name) | $($row.level) | [页面](./$dirName/) |")
}
Write-Utf8File $majorIndex $majorLines.ToString()

$report = Join-Path $DocsRoot "source\pdf-processing-report.md"
$majorCount = ($Manifest | Where-Object { $_.type -eq "major-plan" }).Count
$sharedCount = $Manifest.Count - $majorCount
$reportContent = @"
# PDF 批处理报告

| 字段 | 内容 |
| --- | --- |
| 处理时间 | $GeneratedAt |
| 专业计划 PDF | $majorCount |
| 共享 PDF | $sharedCount |
| Manifest | docs/jiangsu/source/pdf-processing-manifest.csv |

## 输出规则

- 专业计划 PDF：docs/jiangsu/majors/<major>/sources/
- 共享 PDF：docs/jiangsu/source/processed/<category>/<document>/

## 数据状态

本次输出为机器初稿，已完成 raw XML/TXT、基线规范化 HTML、Markdown 草稿和转换记录。课程表级语义化抽取仍需后续人工校对或规则增强。
"@
Write-Utf8File $report $reportContent

Write-Host "Processed $($Manifest.Count) PDFs."
Write-Host "Manifest: $(Get-RelativePath $manifestCsv)"
Write-Host "Report: $(Get-RelativePath $report)"

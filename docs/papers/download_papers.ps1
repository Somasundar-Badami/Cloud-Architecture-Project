# Downloads the free copies of the 15 literature-survey papers into this folder.
# Run from PowerShell inside docs\papers:   powershell -ExecutionPolicy Bypass -File .\download_papers.ps1
$papers = [ordered]@{
  "02_Hassan_FSE2024_State_Reconciliation_Defects.pdf"        = "https://par.nsf.gov/servlets/purl/10540428"
  "03_Abuzakuk_RIVA_2026.pdf"                                  = "https://arxiv.org/pdf/2603.02345"
  "04_Wen_SlsDetector_TOSEM2026.pdf"                           = "https://discovery.ucl.ac.uk/10225136/1/TOSEM_serverless_LLM_configuration_SlsDetector.pdf"
  "05_Rahman_Kubernetes_Manifests_TOSEM2023.pdf"               = "https://par.nsf.gov/servlets/purl/10415562"
  "06_Saavedra_GLITCH_ASE2023.pdf"                             = "https://arxiv.org/pdf/2308.09458"
  "07_Opdebeeck_GASEL_MSR2023.pdf"                             = "https://soft.vub.ac.be/Publications/2023/vub-tr-soft-23-09.pdf"
  "08_Verdet_Terraform_Security_EMSE2025.pdf"                  = "https://arxiv.org/pdf/2308.03952"
  "09_Saavedra_InfraFix_ISSTA2025.pdf"                         = "https://arxiv.org/pdf/2503.17220"
  "13_Rjoub_XAI_Cybersecurity_Survey_2023.pdf"                 = "https://arxiv.org/pdf/2303.12942"
  "14_Mohale_Obagbuwa_XAI_IDS_FrontiersAI2025.pdf"             = "https://www.frontiersin.org/journals/artificial-intelligence/articles/10.3389/frai.2025.1526221/pdf"
  "15_Saleh_AI_Anomaly_Detection_Cloud_CCSW2024.pdf"           = "https://arxiv.org/pdf/2411.09200"
}
foreach ($name in $papers.Keys) {
  try {
    Invoke-WebRequest -Uri $papers[$name] -OutFile $name -UserAgent "Mozilla/5.0" -ErrorAction Stop
    Write-Host "OK      $name"
  } catch {
    Write-Host "FAILED  $name  ->  open manually: $($papers[$name])"
  }
}
Write-Host "`nPapers 1, 10, 11 and 12 need a manual download, see README.md in this folder."

param([Parameter(Mandatory=$true)][string]$Path)
$signature = Get-AuthenticodeSignature -LiteralPath $Path
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') {
    throw 'The downloaded WebView2 bootstrapper does not have a valid Microsoft signature'
}

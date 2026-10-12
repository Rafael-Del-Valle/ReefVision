using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;

internal static class Program
{
    private const string Release = "v1.0.0";
    private const string Version = "1.0.0";
    private const string Owner = "Rafael-Del-Valle";
    private const string Repository = "ReefVision";
    private const string InstallerName = "ReefVision_1.0.0_x64_en-US.msi";

    // Exact file sizes from the published v1.0.0 release. Hashes come from
    // its build-provenance.json. Never download checkpoints or unlisted assets.
    private static readonly Dictionary<string, long> RequiredFiles =
        new(StringComparer.OrdinalIgnoreCase)
        {
            [InstallerName] = 219256893,
            ["rv1.cab"] = 644422556,
            ["rv2.cab"] = 357982458,
            ["rv3.cab"] = 623943306,
            ["rv4.cab"] = 217289426,
            ["rv5.cab"] = 403908961,
            ["rv6.cab"] = 446771134
        };

    private static string AssetUrl(string name) =>
        $"https://github.com/{Owner}/{Repository}/releases/download/{Release}/{name}";

    private sealed record Asset(string Name, long Size, string Sha256);

    public static async Task<int> Main(string[] args)
    {
        Console.Title = "ReefVision Windows downloader";
        Console.WriteLine("ReefVision 1.0.0 — Windows download");
        Console.WriteLine("Downloads the original MSI and all six CAB files from GitHub.");
        Console.WriteLine("No models or other software will be downloaded.");
        Console.WriteLine();

        using var cancellation = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            cancellation.Cancel();
        };

        using var client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = true });
        client.Timeout = Timeout.InfiniteTimeSpan;
        client.DefaultRequestHeaders.UserAgent.ParseAdd("ReefVision-Windows-Downloader/1.0");

        try
        {
            var assets = await ReadReleaseManifestAsync(client, cancellation.Token);
            Console.WriteLine("Release manifest and required files: OK");

            if (args.Length == 1 && args[0] == "--check-release")
            {
                Console.WriteLine("Release metadata check passed. No installer files were downloaded.");
                return 0;
            }

            var downloads = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
                "Downloads",
                "ReefVision-" + Version);
            Directory.CreateDirectory(downloads);
            Console.WriteLine($"Installer folder: {downloads}");
            Console.WriteLine();

            foreach (var asset in assets)
                await EnsureDownloadedAsync(client, asset, downloads, cancellation.Token);

            var installerPath = Path.Combine(downloads, InstallerName);
            Console.WriteLine();
            Console.WriteLine("All seven installer files were downloaded and verified.");
            Console.WriteLine("Press Enter to open the Windows installer, or close this window to install later.");
            Console.ReadLine();

            Process.Start(new ProcessStartInfo(installerPath) { UseShellExecute = true });
            Console.WriteLine("Windows installer opened. Follow its on-screen instructions.");
            return 0;
        }
        catch (OperationCanceledException)
        {
            Console.WriteLine("Download cancelled. Previously verified files are kept.");
            return 2;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine();
            Console.Error.WriteLine("Download could not complete: " + ex.Message);
            Console.Error.WriteLine("Existing verified files are kept. Run the downloader again to retry.");
            if (!Console.IsInputRedirected)
            {
                Console.Error.WriteLine("Press Enter to close.");
                Console.ReadLine();
            }
            return 1;
        }
    }

    private static async Task<IReadOnlyList<Asset>> ReadReleaseManifestAsync(
        HttpClient client, CancellationToken cancellation)
    {
        using var response = await client.GetAsync(
            AssetUrl("build-provenance.json"),
            HttpCompletionOption.ResponseHeadersRead,
            cancellation);
        response.EnsureSuccessStatusCode();
        await using var stream = await response.Content.ReadAsStreamAsync(cancellation);
        using var json = await JsonDocument.ParseAsync(stream, cancellationToken: cancellation);
        var root = json.RootElement;

        if (root.GetProperty("version").GetString() != Version
            || !root.GetProperty("source_tree_clean").GetBoolean()
            || !root.GetProperty("msi_verified").GetBoolean())
            throw new InvalidDataException("The published build provenance is not a verified ReefVision 1.0.0 release.");

        var records = new Dictionary<string, Asset>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in root.GetProperty("files").EnumerateArray())
        {
            var name = entry.GetProperty("name").GetString()
                ?? throw new InvalidDataException("Missing release filename.");
            var hash = entry.GetProperty("sha256").GetString()
                ?? throw new InvalidDataException("Missing SHA-256.");
            if (!RequiredFiles.TryGetValue(name, out long size)
                || !string.Equals(Path.GetFileName(name), name, StringComparison.Ordinal)
                || hash.Length != 64
                || !hash.All(Uri.IsHexDigit)
                || !records.TryAdd(name, new Asset(name, size, hash)))
                throw new InvalidDataException("Release file list does not match the expected Windows installer.");
        }

        if (records.Count != RequiredFiles.Count
            || RequiredFiles.Keys.Any(name => !records.ContainsKey(name)))
            throw new InvalidDataException("The release is missing a required MSI or CAB file.");

        return RequiredFiles.Keys.Select(name => records[name]).ToArray();
    }

    private static async Task EnsureDownloadedAsync(
        HttpClient client, Asset asset, string directory, CancellationToken cancellation)
    {
        var destination = Path.Combine(directory, asset.Name);
        if (File.Exists(destination) && await IsVerifiedAsync(destination, asset, cancellation))
        {
            Console.WriteLine($"Already verified: {asset.Name}");
            return;
        }

        var temp = destination + ".part";
        if (File.Exists(temp))
            File.Delete(temp);

        Console.WriteLine($"Downloading: {asset.Name} ({asset.Size / 1048576.0:F1} MiB)");
        try
        {
            using var response = await client.GetAsync(
                AssetUrl(Uri.EscapeDataString(asset.Name)),
                HttpCompletionOption.ResponseHeadersRead,
                cancellation);
            response.EnsureSuccessStatusCode();
            if (response.Content.Headers.ContentLength is long length && length != asset.Size)
                throw new InvalidDataException("Unexpected download size for " + asset.Name);

            await using var incoming = await response.Content.ReadAsStreamAsync(cancellation);
            await using var outgoing = new FileStream(
                temp, FileMode.CreateNew, FileAccess.Write, FileShare.None, 1048576, useAsync: true);
            using var checksum = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);

            var buffer = new byte[1048576];
            long total = 0;
            int percentShown = -1;
            while (true)
            {
                int read = await incoming.ReadAsync(buffer, cancellation);
                if (read == 0)
                    break;

                await outgoing.WriteAsync(buffer.AsMemory(0, read), cancellation);
                checksum.AppendData(buffer, 0, read);
                total += read;
                int percent = (int)Math.Min(100, total * 100 / asset.Size);
                if (percent / 10 > percentShown / 10)
                {
                    percentShown = percent;
                    Console.Write($"\r  {percent}% complete   ");
                }
                if (total > asset.Size)
                    throw new InvalidDataException("Download exceeded expected file size: " + asset.Name);
            }
            Console.WriteLine();

            var actualHash = Convert.ToHexString(checksum.GetHashAndReset());
            if (total != asset.Size
                || !actualHash.Equals(asset.Sha256, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Size or SHA-256 check failed for " + asset.Name);

            await outgoing.FlushAsync(cancellation);
            outgoing.Close();
            File.Move(temp, destination, overwrite: true);
            Console.WriteLine($"Verified: {asset.Name}");
        }
        finally
        {
            if (File.Exists(temp))
                File.Delete(temp);
        }
    }

    private static async Task<bool> IsVerifiedAsync(
        string path, Asset asset, CancellationToken cancellation)
    {
        if (new FileInfo(path).Length != asset.Size)
            return false;

        await using var file = File.OpenRead(path);
        var hash = await SHA256.HashDataAsync(file, cancellation);
        return Convert.ToHexString(hash).Equals(
            asset.Sha256, StringComparison.OrdinalIgnoreCase);
    }
}

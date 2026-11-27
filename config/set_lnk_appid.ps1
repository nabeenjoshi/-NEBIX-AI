param(
    [Parameter(Mandatory = $true)][string]$LnkPath,
    [Parameter(Mandatory = $true)][string]$AppId,
    [Parameter(Mandatory = $true)][string]$RelaunchCommand,
    [Parameter(Mandatory = $true)][string]$DisplayName,
    [Parameter(Mandatory = $true)][string]$IconResource
)

$definition = @"
using System;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

[ComImport]
[Guid("00021401-0000-0000-C000-000000000046")]
internal class CShellLink {}

[StructLayout(LayoutKind.Sequential, Pack = 4)]
internal struct PropertyKey {
    public Guid fmtid;
    public uint pid;
    public PropertyKey(Guid formatId, uint propertyId) {
        fmtid = formatId;
        pid = propertyId;
    }
}

[StructLayout(LayoutKind.Sequential)]
internal struct PropVariantNative {
    public ushort vt;
    public ushort wReserved1;
    public ushort wReserved2;
    public ushort wReserved3;
    public IntPtr pointerValue;
    public IntPtr extra;
}

[ComImport]
[InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
[Guid("886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99")]
internal interface IPropertyStore {
    void GetCount(out uint cProps);
    void GetAt(uint iProp, out PropertyKey pkey);
    void GetValue(ref PropertyKey key, out PropVariantNative pv);
    void SetValue(ref PropertyKey key, ref PropVariantNative pv);
    void Commit();
}

public static class NebixLnkAppId {
    static readonly Guid FmtId = new Guid("9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3");

    [DllImport("ole32.dll")]
    static extern int PropVariantClear(ref PropVariantNative pvar);

    public static void Apply(
        string lnkPath,
        string appId,
        string relaunchCommand,
        string displayName,
        string iconResource
    ) {
        object raw = new CShellLink();
        var persist = (IPersistFile)raw;
        persist.Load(lnkPath, 0);
        var store = (IPropertyStore)raw;
        SetString(store, 5, appId);
        SetString(store, 2, relaunchCommand);
        SetString(store, 4, displayName);
        SetString(store, 3, iconResource);
        store.Commit();
        persist.Save(lnkPath, true);
        Marshal.FinalReleaseComObject(raw);
    }

    static void SetString(IPropertyStore store, uint pid, string value) {
        var key = new PropertyKey(FmtId, pid);
        var pv = new PropVariantNative();
        pv.vt = 31;
        pv.pointerValue = Marshal.StringToCoTaskMemUni(value);
        try {
            store.SetValue(ref key, ref pv);
        } finally {
            PropVariantClear(ref pv);
        }
    }
}
"@

if (-not ("NebixLnkAppId" -as [type])) {
    Add-Type -TypeDefinition $definition -Language CSharp
}

[NebixLnkAppId]::Apply(
    $LnkPath,
    $AppId,
    $RelaunchCommand,
    $DisplayName,
    $IconResource
)

package com.zhaoxi.app.updater

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.security.MessageDigest

/**
 * 免商店自动更新的原生面：安装调起、未知来源权限、版本与签名读取、网络类型。
 *
 * 全部方法都在 Dart 侧有对应封装（`lib/core/updater/apk_installer.dart`）；异常一律
 * 走 `result.error`，不返回假成功——静默成功会让端侧状态机与真实世界脱节。
 */
class ApkInstaller(private val context: Context) : MethodChannel.MethodCallHandler {

    companion object {
        const val CHANNEL = "com.zhaoxi.app/updater"
        private const val APK_MEDIA_TYPE = "application/vnd.android.package-archive"
        private const val FILE_PROVIDER_SUFFIX = ".fileprovider"
    }

    fun attach(messenger: BinaryMessenger) {
        MethodChannel(messenger, CHANNEL).setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        try {
            when (call.method) {
                "installApk" -> result.success(installApk(call.argument<String>("apkPath")))
                "canInstallPackages" -> result.success(canInstallPackages())
                "openInstallPermissionSettings" -> {
                    openInstallPermissionSettings()
                    result.success(null)
                }
                "installedVersionCode" -> result.success(installedVersionCode())
                "installedSignatureFingerprint" -> result.success(installedSignatureFingerprint())
                "apkSignatureFingerprint" ->
                    result.success(apkSignatureFingerprint(call.argument<String>("apkPath")))
                "isOnWifi" -> result.success(isOnWifi())
                else -> result.notImplemented()
            }
        } catch (error: Exception) {
            result.error("updater", error.message ?: error.javaClass.simpleName, null)
        }
    }

    /** 调起系统安装器；返回 true 表示已成功拉起（不代表用户已确认安装）。 */
    private fun installApk(apkPath: String?): Boolean {
        if (apkPath.isNullOrEmpty()) {
            return false
        }
        val file = File(apkPath)
        if (!file.isFile) {
            return false
        }
        val uri: Uri = FileProvider.getUriForFile(
            context,
            context.packageName + FILE_PROVIDER_SUFFIX,
            file,
        )
        val intent = Intent(Intent.ACTION_VIEW).apply {
            setDataAndType(uri, APK_MEDIA_TYPE)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        }
        context.startActivity(intent)
        return true
    }

    private fun canInstallPackages(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return true
        }
        return context.packageManager.canRequestPackageInstalls()
    }

    private fun openInstallPermissionSettings() {
        val intent = Intent(
            Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
            Uri.parse("package:" + context.packageName),
        ).apply {
            addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        }
        context.startActivity(intent)
    }

    private fun installedVersionCode(): Int {
        val info = context.packageManager.getPackageInfo(context.packageName, 0)
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            info.longVersionCode.toInt()
        } else {
            @Suppress("DEPRECATION")
            info.versionCode
        }
    }

    private fun installedSignatureFingerprint(): String? {
        val info = context.packageManager.getPackageInfo(
            context.packageName,
            PackageManager.GET_SIGNING_CERTIFICATES,
        )
        return fingerprintOf(info)
    }

    private fun apkSignatureFingerprint(apkPath: String?): String? {
        if (apkPath.isNullOrEmpty()) {
            return null
        }
        val info = context.packageManager.getPackageArchiveInfo(
            apkPath,
            PackageManager.GET_SIGNING_CERTIFICATES,
        ) ?: return null
        return fingerprintOf(info)
    }

    /** 与应用身份比对的口径：SHA-256，大写、冒号分隔（与发布侧归一化一致）。 */
    private fun fingerprintOf(info: PackageInfo): String? {
        val signers = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            info.signingInfo?.apkContentsSigners
        } else {
            @Suppress("DEPRECATION")
            info.signatures
        }
        val certificate = signers?.firstOrNull() ?: return null
        val digest = MessageDigest.getInstance("SHA-256").digest(certificate.toByteArray())
        return digest.joinToString(":") { String.format("%02X", it) }
    }

    private fun isOnWifi(): Boolean {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return false
        val network = manager.activeNetwork ?: return false
        val capabilities = manager.getNetworkCapabilities(network) ?: return false
        return capabilities.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) ||
            capabilities.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)
    }
}

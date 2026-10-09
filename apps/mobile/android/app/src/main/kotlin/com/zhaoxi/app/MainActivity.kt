package com.zhaoxi.app

import com.zhaoxi.app.updater.ApkInstaller
import io.flutter.embedding.android.FlutterFragmentActivity
import io.flutter.embedding.engine.FlutterEngine

class MainActivity : FlutterFragmentActivity() {
    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        ApkInstaller(this).attach(flutterEngine.dartExecutor.binaryMessenger)
    }
}

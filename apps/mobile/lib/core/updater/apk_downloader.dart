import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import 'release_api.dart';
import 'release_models.dart';

/// 进度合帧窗口：token/字节到达频率极高，逐字节刷新会让 UI 掉帧。
const Duration progressFrameWindow = Duration(milliseconds: 16);

class DownloadOutcome {
  const DownloadOutcome({
    required this.file,
    required this.receivedBytes,
    required this.totalBytes,
    this.failure,
  });

  final File file;
  final int receivedBytes;
  final int totalBytes;
  final UpdateFailureKind? failure;

  bool get ok => failure == null;
}

/// 流式写盘 + `Range` 续传。
///
/// **关键细节**：续传时若服务端忽略 `Range` 回了 `200`（全量体），必须**截断重写**——
/// 直接追加会拼出损坏文件，而体积校验不一定能拦住（差值巧合时）。
class ApkDownloader {
  ApkDownloader({required ReleaseApi api}) : _opener = api.streamOpener();

  ApkDownloader.withOpener(ArtifactStreamOpener opener) : _opener = opener;

  final ArtifactStreamOpener _opener;

  Future<DownloadOutcome> download({
    required ReleaseArtifact artifact,
    required File target,
    void Function(int received, int total)? onProgress,
    CancelToken? cancelToken,
    Duration frameWindow = progressFrameWindow,
  }) async {
    final existing = await target.exists() ? await target.length() : 0;
    final resumeFrom =
        existing > 0 && existing < artifact.sizeBytes ? existing : 0;

    final ArtifactStreamResponse response;
    try {
      response = await _opener(
        artifact.url,
        startByte: resumeFrom > 0 ? resumeFrom : null,
        cancelToken: cancelToken,
      );
    } on UpdateApiException catch (error) {
      return DownloadOutcome(
        file: target,
        receivedBytes: resumeFrom,
        totalBytes: artifact.sizeBytes,
        failure: error.kind,
      );
    }

    final append = resumeFrom > 0 && response.statusCode == 206;
    if (resumeFrom > 0 && !append && await target.exists()) {
      await target.delete();
    }
    if (append && !await target.exists()) {
      return DownloadOutcome(
        file: target,
        receivedBytes: 0,
        totalBytes: artifact.sizeBytes,
        failure: UpdateFailureKind.incomplete,
      );
    }

    var received = append ? resumeFrom : 0;
    var lastEmit = DateTime.fromMillisecondsSinceEpoch(0);
    final sink = target.openWrite(mode: append ? FileMode.append : FileMode.write);
    UpdateFailureKind? failure;
    try {
      await for (final chunk in response.stream) {
        sink.add(chunk);
        received += chunk.length;
        final now = DateTime.now();
        if (now.difference(lastEmit) >= frameWindow) {
          lastEmit = now;
          onProgress?.call(received, artifact.sizeBytes);
        }
      }
      await sink.flush();
    } on DioException catch (error) {
      failure = dioFailureKind(error);
    } on FileSystemException catch (error) {
      debugPrint('安装包写盘失败：$error');
      failure = UpdateFailureKind.platformError;
    } finally {
      await sink.close();
    }
    onProgress?.call(received, artifact.sizeBytes);
    return DownloadOutcome(
      file: target,
      receivedBytes: received,
      totalBytes: artifact.sizeBytes,
      failure: failure,
    );
  }
}

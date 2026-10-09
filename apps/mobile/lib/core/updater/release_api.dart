import 'package:dio/dio.dart';

import '../env/app_env.dart';
import '../network/dio_client.dart';
import 'release_models.dart';

/// 制品流：把「打开一个可读流」抽象出来，下载器的续传/截断逻辑即可脱离 dio 单测。
typedef ArtifactStreamOpener = Future<ArtifactStreamResponse> Function(
  String url, {
  int? startByte,
  CancelToken? cancelToken,
});

class ArtifactStreamResponse {
  const ArtifactStreamResponse({
    required this.statusCode,
    required this.stream,
  });

  final int statusCode;
  final Stream<List<int>> stream;
}

class UpdateApiException implements Exception {
  const UpdateApiException(this.kind, [this.message]);

  final UpdateFailureKind kind;
  final String? message;

  @override
  String toString() => 'UpdateApiException(${kind.name}${message == null ? '' : ': $message'})';
}

/// 版本接口客户端：只有两个出口——查最新版本、打开制品流。
/// 复用 `createDio()` 的共享实例（自带脱敏与错误映射拦截器），不另建 Dio。
class ReleaseApi {
  ReleaseApi({Dio? dio, String? baseUrl})
      : _dio = dio ?? createDio(),
        _baseUrl = baseUrl ?? AppEnv.apiBaseUrl;

  final Dio _dio;
  final String _baseUrl;

  static const String _apiSuffix = '/api/v1';
  static const String _latestPath = '/app-release/latest';
  static const String _apkMediaType = 'application/vnd.android.package-archive';

  Future<UpdateCheckResult> fetchLatest({
    required String platform,
    required String channel,
    required int versionCode,
  }) async {
    try {
      final response = await _dio.get<Map<String, dynamic>>(
        _latestPath,
        queryParameters: {
          'platform': platform,
          'channel': channel,
          'version_code': versionCode,
        },
      );
      final data = response.data;
      if (data == null) {
        throw const UpdateApiException(UpdateFailureKind.invalidResponse);
      }
      return UpdateCheckResult.parse(data);
    } on DioException catch (error) {
      throw UpdateApiException(dioFailureKind(error), error.message);
    }
  }

  ArtifactStreamOpener streamOpener() {
    return (url, {startByte, cancelToken}) async {
      try {
        final response = await _dio.get<ResponseBody>(
          requestPath(url),
          options: Options(
            responseType: ResponseType.stream,
            // 长下载不能沿用 dio_client 的 15s 空闲超时（那是给流式对话的首 token 预算）
            receiveTimeout: null,
            headers: startByte != null && startByte > 0
                ? {'Range': 'bytes=$startByte-'}
                : null,
            validateStatus: (status) =>
                status != null && status >= 200 && status < 400,
          ),
          cancelToken: cancelToken,
        );
        final body = response.data;
        if (body == null) {
          throw const UpdateApiException(UpdateFailureKind.invalidResponse);
        }
        return ArtifactStreamResponse(
          statusCode: response.statusCode ?? 200,
          stream: body.stream.cast<List<int>>(),
        );
      } on DioException catch (error) {
        throw UpdateApiException(dioFailureKind(error), error.message);
      }
    };
  }

  /// 服务端下发的是带 `/api/v1` 前缀的路径（含代理场景下的 `http` 绝对地址），
  /// 而 dio 的 `baseUrl` 已含该前缀，故此处剥掉前缀只保留路由部分。
  String requestPath(String url) {
    var path = url;
    if (path.startsWith('http')) {
      path = Uri.parse(path).path;
    }
    if (path.startsWith(_apiSuffix)) {
      path = path.substring(_apiSuffix.length);
    }
    return path.isEmpty ? '/' : path;
  }

  String get baseUrl => _baseUrl;

  String mediaType() => _apkMediaType;
}

UpdateFailureKind dioFailureKind(DioException error) {
  switch (error.type) {
    case DioExceptionType.cancel:
      return UpdateFailureKind.cancelled;
    case DioExceptionType.connectionTimeout:
    case DioExceptionType.sendTimeout:
    case DioExceptionType.receiveTimeout:
    case DioExceptionType.transformTimeout:
    case DioExceptionType.connectionError:
    case DioExceptionType.badCertificate:
      return UpdateFailureKind.network;
    case DioExceptionType.badResponse:
      return UpdateFailureKind.invalidResponse;
    case DioExceptionType.unknown:
      return error.error is UpdateFailureKind
          ? error.error! as UpdateFailureKind
          : UpdateFailureKind.network;
  }
}

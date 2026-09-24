enum AppErrorKind {
  networkUnreachable,
  timeout,
  unauthorized,
  badRequest,
  serverError,
  streamInterrupted,
  parseFailure,
}

class AppError implements Exception {
  const AppError({
    required this.kind,
    required this.userMessage,
    this.technicalDetail,
    this.retryable = false,
  });

  final AppErrorKind kind;
  final String userMessage;
  final String? technicalDetail;
  final bool retryable;

  factory AppError.networkUnreachable([String? detail]) => AppError(
        kind: AppErrorKind.networkUnreachable,
        userMessage: '网络好像断了，检查一下再试',
        technicalDetail: detail,
        retryable: true,
      );

  factory AppError.timeout([String? detail]) => AppError(
        kind: AppErrorKind.timeout,
        userMessage: '等太久了，要不要再试一次',
        technicalDetail: detail,
        retryable: true,
      );

  factory AppError.unauthorized([String? detail]) => AppError(
        kind: AppErrorKind.unauthorized,
        userMessage: '需要重新登录一下',
        technicalDetail: detail,
        retryable: false,
      );

  factory AppError.badRequest([String? detail]) => AppError(
        kind: AppErrorKind.badRequest,
        userMessage: '这个操作我没法完成，换个说法试试',
        technicalDetail: detail,
        retryable: false,
      );

  factory AppError.serverError([String? detail]) => AppError(
        kind: AppErrorKind.serverError,
        userMessage: '我这边有点小问题，稍后再试',
        technicalDetail: detail,
        retryable: true,
      );

  factory AppError.streamInterrupted([String? detail]) => AppError(
        kind: AppErrorKind.streamInterrupted,
        userMessage: '刚才没说完，要我接着说吗',
        technicalDetail: detail,
        retryable: true,
      );

  factory AppError.parseFailure([String? detail]) => AppError(
        kind: AppErrorKind.parseFailure,
        userMessage: '我收到了一条看不懂的消息',
        technicalDetail: detail,
        retryable: false,
      );

  factory AppError.fromStatusCode(int status, [String? detail]) {
    if (status == 401 || status == 403) return AppError.unauthorized(detail);
    if (status >= 500) return AppError.serverError(detail);
    if (status >= 400) return AppError.badRequest(detail);
    return AppError.serverError(detail);
  }

  @override
  String toString() => 'AppError(${kind.name}: $userMessage)';
}

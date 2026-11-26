import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/errors/app_error.dart';
import 'package:mobile/core/network/interceptors/error_mapping_interceptor.dart';
import 'package:mobile/core/network/interceptors/log_redaction_interceptor.dart';

void main() {
  test('error messages have no technical details', () {
    for (final e in [
      AppError.networkUnreachable('SocketException'),
      AppError.timeout('15000ms'),
      AppError.unauthorized('401'),
      AppError.badRequest('400'),
      AppError.serverError('500'),
      AppError.streamInterrupted('eof'),
      AppError.parseFailure('FormatException'),
    ]) {
      expect(e.userMessage.contains(RegExp(r'\d{3}')), isFalse);
      expect(e.userMessage.contains('Exception'), isFalse);
      expect(e.userMessage.contains('ms'), isFalse);
    }
    expect(AppError.networkUnreachable().userMessage, '网络好像断了，检查一下再试');
    expect(AppError.timeout().userMessage, '等太久了，要不要再试一次');
    expect(AppError.unauthorized().userMessage, '需要重新登录一下');
  });

  test('status code mapping', () {
    expect(AppError.fromStatusCode(401).kind, AppErrorKind.unauthorized);
    expect(AppError.fromStatusCode(403).kind, AppErrorKind.unauthorized);
    expect(AppError.fromStatusCode(400).kind, AppErrorKind.badRequest);
    expect(AppError.fromStatusCode(500).kind, AppErrorKind.serverError);
  });

  test('dio exception mapping', () {
    final timeout = ErrorMappingInterceptor.mapDioException(
      DioException(
        requestOptions: RequestOptions(path: '/x'),
        type: DioExceptionType.connectionTimeout,
      ),
    );
    expect(timeout.kind, AppErrorKind.timeout);
  });

  test('log redaction hides money health token', () {
    final map = LogRedactionInterceptor.redactMap({
      'method': 'GET',
      'path': '/home',
      'status': 200,
      'amount': '35.00',
      'heart_rate': '72',
      'authorization': 'Bearer xxx',
      'token': 'secret',
    });
    expect(map['method'], 'GET');
    expect(map['amount'], '[redacted]');
    expect(map['heart_rate'], '[redacted]');
    expect(map['authorization'], '[redacted]');
    expect(map['token'], '[redacted]');
  });
}

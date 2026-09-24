import 'package:dio/dio.dart';

import '../errors/app_error.dart';

class ErrorMappingInterceptor extends Interceptor {
  const ErrorMappingInterceptor();

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    handler.next(
      DioException(
        requestOptions: err.requestOptions,
        response: err.response,
        type: err.type,
        error: mapDioException(err),
        stackTrace: err.stackTrace,
      ),
    );
  }

  static AppError mapDioException(DioException err) {
    final status = err.response?.statusCode;
    if (status != null) {
      return AppError.fromStatusCode(status, err.message);
    }
    switch (err.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return AppError.timeout(err.message);
      case DioExceptionType.connectionError:
        return AppError.networkUnreachable(err.message);
      case DioExceptionType.cancel:
        return AppError.streamInterrupted('cancelled');
      default:
        return AppError.networkUnreachable(err.message);
    }
  }
}

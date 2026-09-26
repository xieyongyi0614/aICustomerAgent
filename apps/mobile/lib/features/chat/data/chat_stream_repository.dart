import 'dart:async';

import 'package:dio/dio.dart';

import '../../../core/network/dio_client.dart';
import '../../../core/network/events/chat_event.dart';
import '../../../core/network/interceptors/token_reader.dart';
import '../../../core/network/ndjson/ndjson_parser.dart';
import '../../../core/storage/secure_token_store.dart';

/// 对话流仓储：dio + NDJSON（L3：presentation 不直接碰 dio）。
class ChatStreamRepository {
  ChatStreamRepository({Dio? dio, TokenReader? tokenReader})
      : _dio = dio ??
            createDio(
              tokenReader: tokenReader ?? SecureTokenStore(),
            );

  final Dio _dio;
  final _parser = const NdjsonParser();
  CancelToken? _cancelToken;

  /// [onSessionId]：后端为每次请求返回会话归属（新会话经 X-Session-Id 下发），
  /// 调用方负责持久化，用于下一次进入时拉取历史。
  Stream<ChatEvent> send({
    required String content,
    String? sessionId,
    void Function(String sessionId)? onSessionId,
  }) async* {
    _cancelToken?.cancel('new_turn');
    final cancel = CancelToken();
    _cancelToken = cancel;
    final response = await _dio.post<ResponseBody>(
      '/chat/message',
      data: <String, dynamic>{
        'content': content,
        if (sessionId != null) 'session_id': sessionId as Object,
      },
      options: Options(
        responseType: ResponseType.stream,
        headers: {'Accept': 'application/x-ndjson'},
      ),
      cancelToken: cancel,
    );
    final remoteSessionId = response.headers.value('x-session-id');
    if (remoteSessionId != null && remoteSessionId.isNotEmpty) {
      onSessionId?.call(remoteSessionId);
    }
    final stream = response.data!.stream;
    yield* _parser.parse(stream);
  }

  void cancel() {
    _cancelToken?.cancel('user');
    _cancelToken = null;
  }

  void dispose() => cancel();
}

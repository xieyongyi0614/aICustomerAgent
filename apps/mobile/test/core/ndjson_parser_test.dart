import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:mobile/core/network/events/chat_event.dart';
import 'package:mobile/core/network/ndjson/ndjson_parser.dart';

Stream<List<int>> bytesOf(String s) => Stream.value(Uint8List.fromList(utf8.encode(s)));

Stream<List<int>> chunked(List<String> parts) async* {
  for (final p in parts) {
    yield Uint8List.fromList(utf8.encode(p));
  }
}

void main() {
  const parser = NdjsonParser();

  test('ndjson parses basic events', () async {
    final raw = '{"type":"token","delta":"你好"}\n'
        '{"type":"done"}\n';
    final events = await parser.parse(bytesOf(raw)).toList();
    expect(events.length, 2);
    expect(events[0], isA<TokenDelta>());
    expect(events[1], isA<Done>());
  });

  test('ndjson handles cross-chunk half line', () async {
    final events = await parser
        .parse(chunked([
          '{"type":"token","del',
          'ta":"中"}\n',
        ]))
        .toList();
    expect(events.length, 1);
    final e = events.single as TokenDelta;
    expect(e.delta, '中');
  });

  test('ndjson handles multi-byte utf8 across chunks', () async {
    final full = utf8.encode('{"type":"token","delta":"好"}\n');
    final mid = full.length ~/ 2;
    final events = await parser
        .parse(Stream.fromIterable([
          full.sublist(0, mid),
          full.sublist(mid),
        ]))
        .toList();
    expect(events.single, isA<TokenDelta>());
    expect((events.single as TokenDelta).delta, '好');
  });

  test('ndjson skips empty lines', () async {
    final raw = '\n{"type":"done"}\n\n';
    final events = await parser.parse(bytesOf(raw)).toList();
    expect(events.length, 1);
  });

  test('ndjson illegal json becomes failure without aborting', () async {
    final raw = 'not-json\n{"type":"done"}\n';
    final events = await parser.parse(bytesOf(raw)).toList();
    expect(events.length, 2);
    expect(events[0], isA<Failure>());
    expect(events[1], isA<Done>());
  });

  test('unknown type is fail-closed as failure event', () async {
    final raw = '{"type":"nope"}\n';
    final events = await parser.parse(bytesOf(raw)).toList();
    expect(events.single, isA<Failure>());
  });

  test('tool_step sequence parses', () async {
    final raw = '{"type":"tool_step","step_id":"1","tool_id":"t","label":"记账","status":"running"}\n'
        '{"type":"tool_step","step_id":"1","tool_id":"t","label":"记账","status":"done","target":"已同步到生活 · 记账"}\n'
        '{"type":"done"}\n';
    final events = await parser.parse(bytesOf(raw)).toList();
    expect(events.length, 3);
    expect((events[0] as ToolStep).status, 'running');
    expect((events[1] as ToolStep).status, 'done');
  });

  test('memory_refs omitted vs empty', () async {
    final withRefs = await parser
        .parse(bytesOf(
            '{"type":"turn_meta","memory_refs":[{"id":"1","kind":"preference","label":"旅行"}]}\n'))
        .toList();
    final without = await parser.parse(bytesOf('{"type":"turn_meta"}\n')).toList();
    expect((withRefs.single as TurnMeta).memoryRefs?.length, 1);
    expect((without.single as TurnMeta).memoryRefs, isNull);
  });

  test('stream interrupted when done missing', () async {
    final monitor = ChatStreamMonitor();
    final events = await parser
        .parse(bytesOf('{"type":"token","delta":"a"}\n'))
        .toList();
    for (final e in events) {
      monitor.onEvent(e);
    }
    expect(monitor.incompleteError(), isNotNull);
  });
}

import 'package:flutter/material.dart';

class ChatLedgerPage extends StatelessWidget {
  const ChatLedgerPage({super.key, this.conversationId});

  final String? conversationId;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('AI 记账')),
      body: Center(child: Text('chat-ledger $conversationId')),
    );
  }
}

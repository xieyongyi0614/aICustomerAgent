import 'package:flutter/material.dart';

class ScaffoldLayerMarker extends StatelessWidget {
  const ScaffoldLayerMarker({super.key, required this.domain});

  final String domain;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: Text(domain)),
      body: Center(child: Text(domain)),
    );
  }
}

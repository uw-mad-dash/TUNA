# -*- coding: utf-8 -*-
# Generated by the protocol buffer compiler.  DO NOT EDIT!
# source: message.proto
"""Generated protocol buffer code."""
from google.protobuf import descriptor as _descriptor
from google.protobuf import descriptor_pool as _descriptor_pool
from google.protobuf import symbol_database as _symbol_database
from google.protobuf.internal import builder as _builder
# @@protoc_insertion_point(imports)

_sym_db = _symbol_database.Default()




DESCRIPTOR = _descriptor_pool.Default().AddSerializedFile(b'\n\rmessage.proto\x12\x13\x64istributedtraining\"X\n\x06\x43onfig\x12\x11\n\tdbms_info\x18\x01 \x01(\t\x12\x16\n\x0e\x62\x65nchmark_info\x18\x02 \x01(\t\x12\x0f\n\x07metrics\x18\x03 \x01(\x08\x12\x12\n\nbenchmarks\x18\x04 \x01(\x08\"h\n\nLossConfig\x12\x11\n\tdbms_info\x18\x01 \x01(\t\x12\x16\n\x0e\x62\x65nchmark_info\x18\x02 \x01(\t\x12/\n\x04loss\x18\x03 \x01(\x0e\x32!.distributedtraining.LossFunction\"\x91\x01\n\x0cPerformanace\x12\x12\n\nthroughput\x18\x01 \x01(\x02\x12\x0f\n\x07goodput\x18\x02 \x01(\x02\x12\x12\n\nlatencyp50\x18\x03 \x01(\x02\x12\x12\n\nlatencyp95\x18\x04 \x01(\x02\x12\x12\n\nlatencyp99\x18\x05 \x01(\x02\x12\x0f\n\x07runtime\x18\x06 \x01(\x02\x12\x0f\n\x07metrics\x18\x07 \x01(\t\"\x14\n\x04Loss\x12\x0c\n\x04loss\x18\x01 \x01(\x02\"\x07\n\x05\x45mpty*d\n\x0cLossFunction\x12\x14\n\x10LOSS_UNSPECIFIED\x10\x00\x12\x0b\n\x07LOSS_L1\x10\x01\x12\x0b\n\x07LOSS_L2\x10\x02\x12\x11\n\rLOSS_L1_Level\x10\x03\x12\x11\n\rLOSS_L2_Level\x10\x04\x32\xc4\x02\n\x11\x44istributedWorker\x12R\n\x0e\x45valuateConfig\x12\x1b.distributedtraining.Config\x1a!.distributedtraining.Performanace\"\x00\x12K\n\x0e\x43ollectQueries\x12\x1b.distributedtraining.Config\x1a\x1a.distributedtraining.Empty\"\x00\x12L\n\x0c\x45valuateLoss\x12\x1f.distributedtraining.LossConfig\x1a\x19.distributedtraining.Loss\"\x00\x12@\n\x04Ping\x12\x1a.distributedtraining.Empty\x1a\x1a.distributedtraining.Empty\"\x00\x62\x06proto3')

_globals = globals()
_builder.BuildMessageAndEnumDescriptors(DESCRIPTOR, _globals)
_builder.BuildTopDescriptorsAndMessages(DESCRIPTOR, 'message_pb2', _globals)
if _descriptor._USE_C_DESCRIPTORS == False:
  DESCRIPTOR._options = None
  _globals['_LOSSFUNCTION']._serialized_start=413
  _globals['_LOSSFUNCTION']._serialized_end=513
  _globals['_CONFIG']._serialized_start=38
  _globals['_CONFIG']._serialized_end=126
  _globals['_LOSSCONFIG']._serialized_start=128
  _globals['_LOSSCONFIG']._serialized_end=232
  _globals['_PERFORMANACE']._serialized_start=235
  _globals['_PERFORMANACE']._serialized_end=380
  _globals['_LOSS']._serialized_start=382
  _globals['_LOSS']._serialized_end=402
  _globals['_EMPTY']._serialized_start=404
  _globals['_EMPTY']._serialized_end=411
  _globals['_DISTRIBUTEDWORKER']._serialized_start=516
  _globals['_DISTRIBUTEDWORKER']._serialized_end=840
# @@protoc_insertion_point(module_scope)

#!/usr/bin/env python
# encoding: utf-8
'''

@author: Hey
@email: sanyuan.**@**.com
@tel: 137****6540
@datetime: 2022/11/26 21:02
@project: LucaPCycle
@file: run
@desc: main for model building
'''
import sys
import json
import copy
import logging
import codecs
import argparse
import shutil
from datetime import timedelta
from datasets import load_dataset
import torch.distributed as dist
from subword_nmt.apply_bpe import BPE
from transformers.models.bert.tokenization_bert import BertTokenizer
sys.path.append(".")
sys.path.append("..")
sys.path.append("../src")
from torch.utils.data.dataloader import DataLoader
from datasets.distributed import split_dataset_by_node
try:
    from common.alphabet import Alphabet
    from common.metrics import metrics_multi_class, metrics_binary
    from common.multi_label_metrics import *
    from utils import set_seed, save_labels, get_parameter_number, get_labels, load_trained_model
    from multi_files_stream_dataloader import *
    from trainer import train
    from evaluator import evaluate
    from tester import test
    from lucaprot.models.lucaprot import LucaProt
    from common.model_config import LucaConfig
    from encoder import Encoder
    from batch_converter import BatchConverter
except ImportError:
    from src.common.alphabet import Alphabet
    from src.common.metrics import metrics_multi_class, metrics_binary
    from src.common.multi_label_metrics import *
    from src.utils import set_seed, save_labels, get_parameter_number, get_labels, load_trained_model
    from src.trainer import train
    from src.evaluator import evaluate
    from src.tester import test
    from src.lucaprot.models.lucaprot import LucaProt
    from src.common.model_config import LucaConfig
    from src.encoder import Encoder
    from src.batch_converter import BatchConverter
    from src.multi_files_stream_dataloader import *


logger = logging.getLogger(__name__)


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train_data_dir", default=None, type=str, required=True, help="the train dataset dirpath.")
    parser.add_argument("--dev_data_dir", default=None, type=str, required=True, help="the dev dataset dirpath.")
    parser.add_argument("--test_data_dir", default=None, type=str, required=True, help="the train dataset dirpath.")
    parser.add_argument("--buffer_size", default=10000, type=int, help="how many samples are loaded into memory at once")
    parser.add_argument("--dataset_name", default=None, type=str, required=True, help="dataset name")
    parser.add_argument("--dataset_type", default="protein", type=str, required=True, choices=[
        "protein",
        "protein_protein"
    ],
                        help="dataset type")
    parser.add_argument("--task_type", default="binary_class", type=str, required=True, choices=[
        "multi_label",
        "multi_class",
        "binary_class",
        "regression"
    ],
                        help="task type")
    parser.add_argument("--task_level_type", default="seq_level", type=str, required=True, choices=[
        "token_level",
        "span_level",
        "seq_level",
        "structure_level"
    ],
                        help="task level type")
    parser.add_argument("--model_type", default=None, type=str, required=True,  choices=["lucaprot"],
                        help="the model type of selected")
    parser.add_argument("--input_type", default=None, type=str, required=True,  choices=[
        "seq",
        "matrix",
        "vector",
        "seq_matrix",
        "seq_vector"
    ],
                        help="the input type of selected")
    parser.add_argument("--input_mode", type=str, default="single",  choices=["single", "pair"], help="the input mode")

    parser.add_argument("--seq_subword",  action="store_true", help="whether use subword-level for sequence")
    parser.add_argument("--codes_file",  type=str, default=None, help="the subword codes filepath")

    parser.add_argument("--label_type", default=None, type=str, required=True, help="label type")
    parser.add_argument("--label_filepath", default=None, type=str, required=True, help="the label list filepath")

    parser.add_argument("--output_dir", default=None, type=str, required=True, help="the output dirpath")

    parser.add_argument("--log_dir", default="./logs/", type=str, required=True, help="log dir.")
    parser.add_argument("--tb_log_dir", default="./tb-logs/", type=str, required=True, help="tensorboard log dir.")

    # Other parameters
    parser.add_argument("--config_path", default=None, type=str, required=True, help="the config filepath of the model")
    parser.add_argument("--seq_vocab_path", default=None, type=str, help="sequence token vocab filepath")
    parser.add_argument("--cache_dir", default=None, type=str, help="cache dir path")

    # pooling_type
    parser.add_argument("--seq_pooling_type",  type=str, default=None, choices=[
        "none",
        "first",
        "last",
        "sum",
        "max",
        "avg",
        "attentive",
        "attention",
        "context_attention",
        "weighted_attention",
        "value_attention",
        "transformer"
    ],
                        help="pooling type for sequence encoder")
    parser.add_argument("--matrix_pooling_type",  type=str, default=None, choices=[
        "none",
        "first",
        "last",
        "sum",
        "max",
        "avg",
        "attentive",
        "attention",
        "context_attention",
        "weighted_attention",
        "value_attention",
        "transformer"
    ],
                        help="pooling type for embedding encoder")
    # fusion type
    parser.add_argument("--fusion_type", default="concat", type=str, required=True,
                        choices=["concat", "add"], help="the fusion type")

    parser.add_argument("--do_train", action="store_true", help="whether to run training.")
    parser.add_argument("--do_eval", action="store_true", help="whether to run eval on the dev set.")
    parser.add_argument("--do_predict", action="store_true", help="whether to run predict on the test set.")
    parser.add_argument("--do_metrics", action="store_true", help="whether to eval metrics on the dev and test set.")

    parser.add_argument("--evaluate_during_training", action="store_true", help="whether to eval during training at each logging step.")
    parser.add_argument("--do_lower_case", action="store_true", help="set this flag if you are using an uncased model.")

    parser.add_argument("--per_gpu_train_batch_size", default=16, type=int, help="Batch size per GPU/CPU for training.")
    parser.add_argument("--per_gpu_eval_batch_size", default=16, type=int, help="Batch size per GPU/CPU for evaluation.")
    parser.add_argument("--gradient_accumulation_steps", type=int, default=1, help="Number of updates steps to accumulate before performing a backward/update pass.")
    parser.add_argument("--learning_rate", default=1e-4, type=float, help="The initial learning rate for Adam.")
    parser.add_argument("--weight_decay", default=0.01, type=float, help="Weight decay if we apply some.")
    parser.add_argument("--adam_epsilon", default=1e-8, type=float, help="Epsilon for Adam optimizer.")
    parser.add_argument("--max_grad_norm", default=1.0, type=float, help="Max gradient norm.")
    parser.add_argument("--num_train_epochs", default=50, type=int, help="Total number of training epochs to perform.")
    parser.add_argument("--max_steps", default=-1, type=int, help="Set total number of training steps to perform.")
    parser.add_argument("--warmup_steps", default=-1, type=int, help="Linear warmup over warmup_steps.")
    parser.add_argument("--beta1", default=0.9, type=float, help="Adamw beta1.")
    parser.add_argument("--beta2", default=0.98, type=float, help="Adamw beta2.")
    parser.add_argument("--lr_update_strategy", default="step", choices=["step", "epoch"], type=str, help="Learning rate update strategy.")
    parser.add_argument("--lr_decay_rate", default=0.9, type=float, help="Learning rate decay rate.")

    parser.add_argument("--logging_steps", type=int, default=-1, help="Log every X updates steps.")
    parser.add_argument("--save_steps", type=int, default=-1, help="Save checkpoint every X updates steps.")
    parser.add_argument("--eval_all_checkpoints", action="store_true", help="Evaluate all checkpoints starting with the same prefix as model_name ending and ending with step number")
    parser.add_argument("--no_cuda", action="store_true", help="Avoid using CUDA when available")
    parser.add_argument("--overwrite_output_dir", action="store_true", help="Overwrite the content of the output directory")
    parser.add_argument("--overwrite_cache", action="store_true", help="Overwrite the cached training and evaluation sets")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for initialization")

    parser.add_argument("--fp16", action="store_true", help="Whether to use 16-bit (mixed) precision (through NVIDIA apex) instead of 32-bit")
    parser.add_argument("--fp16_opt_level", type=str, default="O1", help="For fp16: Apex AMP optimization level selected in ['O0', 'O1', 'O2', and 'O3']." "See details at https://nvidia.github.io/apex/amp.html")
    parser.add_argument("--local_rank", type=int, default=-1, help="For distributed training: local_rank")

    # multi-label/binary-class
    parser.add_argument("--sigmoid", action="store_true", help="Classifier add sigmoid if task_type is binary-class or multi-label")

    # loss func
    parser.add_argument("--loss_type",  type=str, default="bce",
                        choices=["focal_loss", "bce", "multilabel_cce", "asl", "cce", "l1", "l2"],
                        help="Loss type")

    # which metric for model finalization selected
    parser.add_argument("--best_metric_type", type=str, default="f1",
                        choices=[
                            "loss", "acc", "jaccard",
                            "prec", "recall", "f1",
                            "fmax", "roc_auc", "pr_auc",
                            "mcc", "sp_statistic", "mse",
                            "mae", "r2"
                        ],
                        help="Which metric for model selected")
    # for BCE Loss
    parser.add_argument("--pos_weight", type=float, default=1.0, help="positive weight for bce")

    # for CE Loss
    parser.add_argument("--weight", type=str, default=None, help="every label weight for multi-class")

    # for focal Loss
    parser.add_argument("--focal_loss_alpha", type=float, default=0.7, help="focal loss alpha")
    parser.add_argument("--focal_loss_gamma", type=float, default=2.0, help="focal loss gamma")
    parser.add_argument("--focal_loss_reduce", action="store_true", help="mean for one sample(default sum)")

    # for asymmetric Loss
    parser.add_argument("--asl_gamma_neg", type=float, default=4.0, help="negative gamma for asl")
    parser.add_argument("--asl_gamma_pos", type=float, default=1.0, help="positive gamma for asl")

    # for sequence and structure graph node size(contact map shape)
    parser.add_argument("--seq_max_length", default=None, type=int, help="the length of input sequence more than max length will be truncated, shorter will be padded.")

    parser.add_argument("--no_token_embeddings", action="store_true", help="Whether not to use token_embeddings")
    parser.add_argument("--no_position_embeddings", action="store_true", help="Whether not to use position_embeddings")
    parser.add_argument("--no_token_type_embeddings", action="store_true", help="Whether not to use token_type_embeddings")

    parser.add_argument("--position_embedding_type", default="absolute", type=str,  choices=["absolute", "RoPE"], help="the position embedding type.")

    # for embedding input
    parser.add_argument("--embedding_input_size", default=None, type=int, help="the length of input embedding dim.")
    parser.add_argument("--matrix_max_length", default=2048, type=int, help="the length of input embedding more than max length will be truncated, shorter will be padded.")
    parser.add_argument("--matrix_encoder", action="store_true", help="Whether to use matrix encoder")
    parser.add_argument("--matrix_encoder_act", action="store_true", help="Whether to use matrix encoder activate function")

    parser.add_argument("--trunc_type", default="right", type=str, required=True,  choices=["left", "right"], help="truncate type for whole input")

    # 再次训练加载已经训练好的模型
    parser.add_argument("--model_dirpath", default=None, type=str, help="load the trained model to continue training.")
    parser.add_argument("--save_all",  action="store_true", help="save all check-point")
    parser.add_argument("--delete_old",  action="store_true", help="delete old check-point")

    # encoder
    parser.add_argument("--hidden_size", default=None, type=int, help="hidden size for encoder.")
    parser.add_argument("--intermediate_size", default=None, type=int, help="intermediate size for encoder.")
    parser.add_argument("--num_attention_heads",  default=None, type=int, help="num attention_heads for encoder")
    parser.add_argument("--num_hidden_layers",  default=None, type=int, help="num hidden_layers for encoder")
    parser.add_argument("--dropout_prob",  default=None, type=float, help="dropout prob for encoder")

    # classifier
    parser.add_argument("--classifier_size", default=None, type=int, help="hidden size for classifier.")

    # llm
    parser.add_argument("--llm_dir", default=None, type=str, help="llm dir.")
    parser.add_argument("--llm_type", default=None, type=str, choices=["esm", "lucaone_gplm"], required=True, help="llm type.")
    parser.add_argument("--llm_version", type=str, default="v2.0", choices=["v0.1", "v0.2", "v1.2", "v2.0", "esm2", "esm1"], help="llm version")
    parser.add_argument("--llm_task_level", type=str, default="token_level,span_level,seq_level,structure_level",
                        choices=["token_level", "token_level,span_level,seq_level,structure_level"],
                        help="llm task level")
    parser.add_argument("--llm_time_str", type=str, default=None,  help="llm time str")
    parser.add_argument("--llm_step", type=int, default=None, help="llm step.")

    # others
    parser.add_argument("--ignore_index", type=int, default=-100,  help="ignore index")
    parser.add_argument("--non_ignore",  action="store_true", help="none ignore.")

    parser.add_argument("--vector_dirpath", type=str, default=None,  help="vector dirpath")
    parser.add_argument("--matrix_dirpath", type=str, default=None,  help="matrix dirpath")

    parser.add_argument("--seq_fc_size", default=None, type=str, help="seq fc size.")
    parser.add_argument("--matrix_fc_size", default=None, type=str, help="matrix fc size.")
    parser.add_argument("--vector_fc_size", default=None, type=str, help="vector fc size.")
    parser.add_argument("--emb_activate_func", default="tanh", type=str, help="emb activate func.")
    parser.add_argument("--fc_activate_func", default="tanh", type=str, help="fc activate func.")
    parser.add_argument("--classifier_activate_func", default="tanh", type=str, help="classifier activate func.")

    parser.add_argument("--not_prepend_bos",  action="store_true", help="not prepend_bos")
    parser.add_argument("--not_append_eos", action="store_true",  help="not append_eos")
    parser.add_argument("--loss_reduction", default="mean", choices=["none", "meansum", "mean", "meanmean"], type=str, help="loss reduction")
    parser.add_argument("--cross_atten",  action="store_true", help="use cross attention")
    parser.add_argument("--self_atten", action="store_true",  help="use self attention")

    # for pair
    parser.add_argument("--seq_max_length_a", default=None, type=int, help="the length of input atom sequence more than max length will be truncated, shorter will be padded.")
    parser.add_argument("--matrix_max_length_a", default=None, type=int, help="the length of input atom embedding more than max length will be truncated, shorter will be padded.")
    parser.add_argument("--embedding_input_size_a", default=None, type=int, help="a embedding_input_size")

    parser.add_argument("--seq_max_length_b", default=None, type=int, help="the length of input atom sequence more than max length will be truncated, shorter will be padded.")
    parser.add_argument("--matrix_max_length_b", default=None, type=int, help="the length of input atom embedding more than max length will be truncated, shorter will be padded.")
    parser.add_argument("--embedding_input_size_b", default=None, type=int, help="b embedding_input_size")

    parser.add_argument("--not_seq_encoder_shared", action="store_true",  help="shared the seq encoder for two kind of seq types")
    parser.add_argument("--not_matrix_encoder_shared", action="store_true",  help="shared the seq encoder for two kind of matrix types")

    parser.add_argument('--worker_num', default=1, type=int, help='worker number for the data loader.')
    args = parser.parse_args()
    return args


def check_args(args):
    if args.input_type in ["seq", "seq_vector", "seq_matrix"]:
        args.no_token_embeddings = False
    else:
        args.no_token_embeddings = True
    return args


def get_input_cols(args):
    if args.input_mode == "single" and args.input_type == "seq":
        input_col_names = [args.dataset_type, "seq"]
    elif args.input_mode == "single" and args.input_type == "vector":
        input_col_names = [args.dataset_type, "embedding_vector"]
    elif args.input_mode == "single" and args.input_type == "matrix":
        input_col_names = [args.dataset_type, "embedding_matrix"]
    elif args.input_mode == "single" and args.input_type == "seq_matrix":
        input_col_names = [args.dataset_type, "seq", "embedding_matrix"]
    elif args.input_mode == "single" and args.input_type == "seq_vector":
        input_col_names = [args.dataset_type, "seq", "embedding_vector"]
    elif args.input_mode == "pair" and args.input_type == "seq":
        input_col_names = [args.dataset_type, "seq_a", "seq_b"]
    elif args.input_mode == "pair" and args.input_type == "vector":
        input_col_names = [args.dataset_type, "embedding_vector_a", "embedding_vector_b"]
    elif args.input_mode == "pair" and args.input_type == "matrix":
        input_col_names = [args.dataset_type, "embedding_matrix_a", "embedding_matrix_b"]
    elif args.input_mode == "pair" and args.input_type == "seq_matrix":
        input_col_names = [args.dataset_type, "seq_a", "seq_b", "embedding_matrix_a", "embedding_matrix_b"]
    elif args.input_mode == "pair" and args.input_type == "seq_vector":
        input_col_names = [args.dataset_type, "seq_a", "seq_b", "embedding_vector_a", "embedding_vector_b"]
    else:
        raise Exception("Not support input_mode=%s" % args.input_mode)
    return input_col_names


def get_label_size(label_filepath):
    '''
    load label size
    :param label_filepath: label list
    :return:
    '''
    if label_filepath:
        cur_labels = get_labels(label_filepath, header=True if label_filepath.endswith(".csv") else False)
        return len(cur_labels)
    else:
        raise Exception("Label path: %s not exists." % label_filepath)


def create_logger(args):
    '''
    create logger
    :param args:
    :return:
    '''
    if args.local_rank in [-1, 0]:
        print("args.local_rank: %d" % args.local_rank)
        # create the output dir
        if os.path.exists(args.output_dir):
            raise ValueError("Output directory ({}) already exists and is not empty.".format(args.output_dir))
        else:
            os.makedirs(args.output_dir)
        # create the logs dir
        if not os.path.exists(args.log_dir):
            os.makedirs(args.log_dir)
        log_fp = open(os.path.join(args.log_dir, "logs.txt"), "w")
        # create tensorboard logs dir
        if not os.path.exists(args.tb_log_dir):
            os.makedirs(args.tb_log_dir)
        if not os.path.exists(args.vector_dirpath):
            os.makedirs(args.vector_dirpath)
        if not os.path.exists(args.matrix_dirpath):
            os.makedirs(args.matrix_dirpath)
    else:
        log_fp = None
    return log_fp


def get_model(args):
    '''
    create tokenizer, model config, model
    :param args:
    :return:
    '''
    if args.task_type not in ["regression"]:
        label_list = get_labels(args.label_filepath, True if args.label_filepath.endswith(".csv") else False)
        num_labels = len(label_list)
        print("num_labels: %d" % num_labels)
    else:
        num_labels = 1
        label_list = ["0"]
        print("num_labels: %d" % num_labels)
    if args.local_rank in [-1, 0]:
        logger.info("#" * 25 + "Labels Num:" + "#" * 25)
        logger.info("Num Labels: %d" % num_labels)
        save_labels(os.path.join(args.log_dir, "label.txt"), label_list)

    args.label_size = num_labels

    model_config = LucaConfig.from_json_file(args.config_path)
    '''
    model_config.seq_max_length = int(args.seq_max_length)
    model_config.matrix_max_length = int(args.matrix_max_length)
    '''
    if args.input_mode in ["pair"]:
        assert args.seq_max_length is not None or (args.seq_max_length_a is not None and args.seq_max_length_b is not None)
        model_config.seq_max_length = args.seq_max_length
        if args.seq_max_length_a is not None and args.seq_max_length_b is not None:
            model_config.seq_max_length_a = args.seq_max_length_a
            model_config.seq_max_length_b = args.seq_max_length_b
        else:
            model_config.seq_max_length_a = args.seq_max_length
            model_config.seq_max_length_b = args.seq_max_length
        model_config.seq_max_length = max(model_config.seq_max_length_a, model_config.seq_max_length_b)

        assert args.matrix_max_length is not None or (args.matrix_max_length_a is not None and args.matrix_max_length_b is not None)
        model_config.matrix_max_length = args.matrix_max_length
        if args.matrix_max_length_a is not None and args.matrix_max_length_b is not None:
            model_config.matrix_max_length_a = args.matrix_max_length_a
            model_config.matrix_max_length_b = args.matrix_max_length_b
        else:
            model_config.matrix_max_length_a = args.matrix_max_length
            model_config.matrix_max_length_b = args.matrix_max_length
        model_config.matrix_max_length = max(model_config.matrix_max_length_a, model_config.matrix_max_length_b)

        assert args.embedding_input_size is not None or (args.embedding_input_size_a is not None and args.embedding_input_size_b is not None)
        model_config.embedding_input_size = args.embedding_input_size
        if args.embedding_input_size_a is not None and args.embedding_input_size_b is not None:
            model_config.embedding_input_size_a = args.embedding_input_size_a
            model_config.embedding_input_size_b = args.embedding_input_size_b
        else:
            model_config.embedding_input_size_a = args.embedding_input_size
            model_config.embedding_input_size_b = args.embedding_input_size
        model_config.embedding_input_size = max(model_config.embedding_input_size_a, model_config.embedding_input_size_b)
    else:
        assert args.seq_max_length is not None
        model_config.seq_max_length = args.seq_max_length
        assert args.matrix_max_length is not None
        model_config.matrix_max_length = args.matrix_max_length
        assert args.embedding_input_size is not None
        model_config.embedding_input_size = args.embedding_input_size

    model_config.num_labels = num_labels
    model_config.seq_pooling_type = args.seq_pooling_type
    model_config.matrix_pooling_type = args.matrix_pooling_type

    if args.hidden_size:
        model_config.hidden_size = args.hidden_size
    if args.intermediate_size:
        model_config.intermediate_size = args.intermediate_size
    if args.num_attention_heads:
        model_config.num_attention_heads = args.num_attention_heads
    if args.num_hidden_layers:
        model_config.num_hidden_layers = args.num_hidden_layers
    if args.dropout_prob is not None and args.dropout_prob > -1:
        model_config.attention_probs_dropout_prob = args.dropout_prob
        model_config.classifier_dropout_prob = args.dropout_prob
        model_config.hidden_dropout_prob = args.dropout_prob
    if args.position_embedding_type is not None:
        model_config.position_embedding_type = args.position_embedding_type
    model_config.ignore_index = args.ignore_index
    model_config.no_token_embeddings = args.no_token_embeddings
    model_config.no_token_type_embeddings = args.no_token_type_embeddings
    model_config.no_position_embeddings = args.no_position_embeddings
    if args.seq_fc_size and args.seq_fc_size != "null":
        model_config.seq_fc_size = [int(v) for v in args.seq_fc_size.split(",")]
    if args.matrix_fc_size and args.matrix_fc_size != "null":
        model_config.matrix_fc_size = [int(v) for v in args.matrix_fc_size.split(",")]
    if args.vector_fc_size and args.vector_fc_size != "null":
        model_config.vector_fc_size = [int(v) for v in args.vector_fc_size.split(",")]
    if args.emb_activate_func and args.emb_activate_func != "null":
        model_config.emb_activate_func = args.emb_activate_func
    if args.fc_activate_func and args.fc_activate_func != "null":
        model_config.fc_activate_func = args.fc_activate_func
    if args.classifier_activate_func and args.classifier_activate_func != "null":
        model_config.classifier_activate_func = args.classifier_activate_func
    args.prepend_bos = True
    if args.not_prepend_bos:
        args.prepend_bos = False
    args.append_eos = True
    if args.not_append_eos:
        args.append_eos = False
    model_config.self_atten = args.self_atten
    model_config.cross_atten = args.cross_atten

    model_config.max_position_embeddings = args.seq_max_length + int(args.prepend_bos) + int(args.append_eos)

    if args.classifier_size:
        model_config.classifier_size = args.classifier_size
    if args.pos_weight:
        model_config.pos_weight = args.pos_weight
    if args.weight:
        model_config.weight = [float(v) for v in args.weight.split(",")]
        args.weight = model_config.weight
    if args.loss_reduction:
        if args.loss_reduction in ["meanmean", "meansum"] \
                and args.task_level_type in ["seq_level"] \
                and args.task_type not in ["multi_label", "multi-label"]:
            args.loss_reduction = "mean"
        model_config.loss_reduction = args.loss_reduction

    if args.seq_subword:
        seq_tokenizer_class = BertTokenizer
        seq_tokenizer = BertTokenizer(args.seq_vocab_path, do_lower_case=args.do_lower_case)
        bpe_codes = codecs.open(args.codes_file)
        seq_subword = BPE(bpe_codes, merges=-1, separator='')
        model_config.cls_token_id = seq_tokenizer.cls_token_id
        model_config.sep_token_id = seq_tokenizer.sep_token_id
    else:
        seq_subword = None
        seq_tokenizer_class = Alphabet
        seq_tokenizer = Alphabet.from_predefined(args.seq_vocab_path)
        if args.not_prepend_bos:
            seq_tokenizer.prepend_bos = False
        if args.not_append_eos:
            seq_tokenizer.append_eos = False
        model_config.cls_token_id = seq_tokenizer.cls_idx
        model_config.sep_token_id = seq_tokenizer.eos_idx
    model_config.vocab_size = seq_tokenizer.vocab_size
    args.vocab_size = seq_tokenizer.vocab_size
    model_config.pad_token_id = seq_tokenizer.pad_token_id

    # model class
    if args.model_type == "lucaprot":
        model_class = LucaProt
    else:
        raise Exception("Not support the model_type=%s" % args.model_type)

    if args.model_dirpath and os.path.exists(args.model_dirpath):
        model = load_trained_model(model_config, args, model_class, args.model_dirpath)
    else:
        model = model_class(model_config, args)

    return model_config, model_class, model, seq_subword, seq_tokenizer_class, seq_tokenizer, label_list


def create_device(args):
    '''
    create device
    :param args:
    :return:
    '''
    if args.no_cuda or not torch.cuda.is_available():
        device = torch.device("cpu")
        args.n_gpu = 0
    else:
        args.n_gpu = torch.cuda.device_count()
        if args.n_gpu > 1:
            torch.cuda.set_device(args.local_rank)
            device = torch.device("cuda", args.local_rank)
            dist.init_process_group(backend="nccl", timeout=timedelta(seconds=54000))
            if args.local_rank == 0:
                print('world size: %d' % dist.get_world_size())
        else:
            device = torch.device("cuda")
    print("create_device:", device)
    return device


def main():
    # get args
    args = get_args()

    # check args
    args = check_args(args)

    # create log dir
    log_fp = create_logger(args)

    # the output type
    args.output_mode = args.task_type
    # For binary_class/multi_label tasks, the sigmoid needs to be added to the last layer
    if args.output_mode in [
        "multi_label", "multi-label",
        "binary_class", "binary-class"
    ]:
        args.sigmoid = True
    elif args.output_mode in [
        "multi_class", "multi-class"
    ]:
        args.sigmoid = False

    # device
    args.device = create_device(args)

    # create model
    model_config, model_class, model, seq_subword, seq_tokenizer_class, seq_tokenizer, label_list = get_model(args)

    if args.llm_type != "esm":
        # to do for other llm, example: lucaone
        llm_dirpath = None
    else:
        llm_dirpath = None
    args.llm_dirpath = llm_dirpath
    # encoder config
    if args.input_mode in ["pair"]:
        assert args.seq_max_length is not None or (args.seq_max_length_a is not None and args.seq_max_length_b is not None)
        if args.seq_max_length is None:
            args.seq_max_length = max(args.seq_max_length_a, args.seq_max_length_b)
    else:
        assert args.seq_max_length is not None
    # encoder_config
    encoder_config = {
        "llm_type": args.llm_type,
        "llm_version": args.llm_version,
        "llm_step": args.llm_step,
        "llm_dirpath": llm_dirpath,
        "input_type": args.input_type,
        "trunc_type": args.trunc_type,
        "seq_max_length": args.seq_max_length,
        "vector_dirpath": args.vector_dirpath,
        "matrix_dirpath": args.matrix_dirpath,
        "prepend_bos": True,
        "append_eos": True,
        "local_rank": args.local_rank
    }

    # file row parser
    # 文件记录解析函数
    encoder = Encoder(**encoder_config)
    # pair对数据集
    if args.input_mode in ["pair"]:
        parse_row_func = encoder.encode_pair
    else:
        # 基因或者蛋白单记录数据集
        parse_row_func = encoder.encode_single

    # encoding
    # batch转换器
    batch_data_func = BatchConverter(
        task_level_type=args.task_level_type,
        label_size=args.label_size,
        output_mode=args.output_mode,
        seq_subword=seq_subword,
        seq_tokenizer=seq_tokenizer,
        no_position_embeddings=model_config.no_position_embeddings,
        no_token_type_embeddings=model_config.no_token_type_embeddings,
        truncation_seq_length=model_config.seq_max_length,
        truncation_matrix_length=model_config.matrix_max_length,
        ignore_index=model_config.ignore_index,
        non_ignore=args.non_ignore,
        padding_idx=0,
        unk_idx=1,
        cls_idx=2,
        eos_idx=3,
        mask_idx=4,
        prepend_bos=not args.not_prepend_bos,
        append_eos=not args.not_append_eos
    )
    if args.local_rank in [0, -1]:
        print("n_gpu: %d" % args.n_gpu)
        args_dict = {}
        for attr, value in sorted(args.__dict__.items()):
            if attr != "device":
                args_dict[attr] = value
            else:
                args_dict[attr] = str(value)
        log_fp.write(json.dumps(args_dict, ensure_ascii=False) + "\n")
        log_fp.write("#" * 50 + "\n")
        log_fp.write("n_gpu: %d\n" % args.n_gpu)
        log_fp.write("#" * 50 + "\n")
        # input types
        input_col_names = get_input_cols(args)
        log_fp.write("Inputs:\n")
        log_fp.write("Input Name List: %s\n" % ",".join(input_col_names))
        log_fp.write("#" * 50 + "\n")

        # output model hyperparameters in logger
        if len(model_config.id2label) > 10:
            str_config = copy.deepcopy(model_config)
            str_config.id2label = {}
            str_config.label2id = {}
        else:
            str_config = copy.deepcopy(model_config)
        log_fp.write("Encoder Config:\n %s\n" % str(encoder_config))
        log_fp.write("#" * 50 + "\n")
        log_fp.write("Model Config:\n %s\n" % str(str_config))
        log_fp.write("#" * 50 + "\n")
        log_fp.write("Mode Architecture:\n %s\n" % str(model))
        log_fp.write("#" * 50 + "\n")
        log_fp.write("Model parameters: %d \n" % sum(p.numel() for p in model.parameters()))
        log_fp.write("#" * 50 + "\n")

        # model size
        model_size_info = get_parameter_number(model)
        log_fp.write(json.dumps(model_size_info, ensure_ascii=False) + "\n")
        log_fp.write("#" * 50 + "\n")
        log_fp.flush()

    # Set seed
    set_seed(args)

    # model to device
    model.to(args.device)

    if args.local_rank not in [-1, 0]:
        dist.barrier()

    if args.local_rank == 0:
        dist.barrier()

    if args.n_gpu <= 1:
        print("n_gpu: %d, use: MultiFilesStreamLoader" % args.n_gpu)
        train_dataloader = MultiFilesStreamLoader(
            args.train_data_dir,
            args.per_gpu_train_batch_size,
            args.buffer_size,
            parse_row_func=parse_row_func,
            batch_data_func=batch_data_func,
            task_level_type=args.task_level_type,
            input_mode=args.input_mode,
            input_type=args.input_type,
            output_mode=args.output_mode,
            label_size=args.label_size,
            dataset_type="train",
            vector_dirpath=args.vector_dirpath,
            matrix_dirpath=args.matrix_dirpath,
            inference=False,
            header=True,
            shuffle=True,
            seed=args.seed
        )
    else:
        print("n_gpu: %d, use: DataLoader" % args.n_gpu)
        train_dataset = load_dataset('csv',
                                     data_dir=args.train_data_dir,
                                     split='train',
                                     streaming=True)
        if args.input_mode == "pair":
            print("Has Pair: True")
            train_dataset = train_dataset.map(
                lambda x: parse_row_func(
                    x["seq_id_a"],
                    x["seq_id_b"],
                    x["seq_type_a"] if "seq_type_a" in x else "prot",
                    x["seq_type_b"] if "seq_type_b" in x else "prot",
                    x["seq_a"],
                    x["seq_b"],
                    x["vector_filename_a"] if "vector_filename_a" in x else None,
                    x["vector_filename_b"] if "vector_filename_b" in x else None,
                    x["matrix_filename_a"] if "matrix_filename_a" in x else None,
                    x["matrix_filename_b"] if "matrix_filename_b" in x else None,
                    x["label"] if "label" in x else None,
                ),
                batched=False
            )
        else:
            print("Has Pair: False")
            train_dataset = train_dataset.map(
                lambda x: parse_row_func(
                    x["seq_id"],
                    x["seq_type"] if "seq_type" in x else "prot",
                    x["seq"],
                    x["vector_filename"] if "vector_filename" in x else None,
                    x["matrix_filename"] if "matrix_filename" in x else None,
                    x["label"] if "label" in x else None,
                ),
                batched=False
            )
        train_dataset = split_dataset_by_node(train_dataset, rank=args.local_rank, world_size=dist.get_world_size()) \
            .shuffle(buffer_size=args.buffer_size, seed=args.seed)
        train_dataset = train_dataset.with_format("torch")
        # train_sampler = DistributedSampler(train_dataset)
        train_dataloader = DataLoader(
            dataset=train_dataset,
            batch_size=args.per_gpu_train_batch_size,
            num_workers=args.worker_num,
            pin_memory=True,
            collate_fn=batch_data_func
        )

    # Training
    max_metric_model_info = None
    if args.do_train:
        logger.info("++++++++++++Training+++++++++++++")
        global_step, tr_loss, max_metric_model_info = train(
            args, train_dataloader, model_config, model, seq_tokenizer, parse_row_func, batch_data_func, train_sampler=None, log_fp=log_fp)
        logger.info("global_step = %s, average loss = %s", global_step, tr_loss)

    # save
    if args.do_train and args.local_rank in [-1, 0]:
        logger.info("++++++++++++Save Model+++++++++++++")
        # Create output directory if needed
        best_output_dir = os.path.join(args.output_dir, "best")
        global_step = max_metric_model_info["global_step"]
        prefix = "checkpoint-{}".format(global_step)
        shutil.copytree(os.path.join(args.output_dir, prefix), best_output_dir)
        logger.info("Saving model checkpoint to %s", best_output_dir)
        torch.save(args, os.path.join(best_output_dir, "training_args.bin"))
        save_labels(os.path.join(best_output_dir, "label.txt"), label_list)

    # evaluate
    if args.do_eval and args.local_rank in [-1, 0]:
        logger.info("++++++++++++Validation+++++++++++++")
        log_fp.write("++++++++++++Validation+++++++++++++\n")
        global_step = max_metric_model_info["global_step"]
        logger.info("best %s global step: %d" % (args.best_metric_type, global_step))
        log_fp.write("best %s global step: %d\n" % (args.best_metric_type, global_step))
        prefix = "checkpoint-{}".format(global_step)
        checkpoint = os.path.join(args.output_dir, prefix)
        if seq_tokenizer is None and seq_tokenizer_class:
            seq_tokenizer = seq_tokenizer_class.from_pretrained(checkpoint, do_lower_case=args.do_lower_case)

        logger.info("checkpoint path: %s" % checkpoint)
        log_fp.write("checkpoint path: %s\n" % checkpoint)
        model = model_class.from_pretrained(checkpoint, args=args)
        model.to(args.device)
        result = evaluate(args, model, parse_row_func, batch_data_func, prefix=prefix, log_fp=log_fp)
        result = dict(("evaluation_" + k + "_{}".format(global_step), v) for k, v in result.items())
        logger.info(json.dumps(result, ensure_ascii=False))
        log_fp.write(json.dumps(result, ensure_ascii=False) + "\n")

    # Testing
    if args.do_predict and args.local_rank in [-1, 0]:
        logger.info("++++++++++++Testing+++++++++++++")
        log_fp.write("++++++++++++Testing+++++++++++++\n")
        global_step = max_metric_model_info["global_step"]
        logger.info("best %s global step: %d" % (args.best_metric_type, global_step))
        log_fp.write("best %s global step: %d\n" % (args.best_metric_type, global_step))
        prefix = "checkpoint-{}".format(global_step)
        checkpoint = os.path.join(args.output_dir, prefix)
        if seq_tokenizer is None and seq_tokenizer_class:
            seq_tokenizer = seq_tokenizer_class.from_pretrained(checkpoint, do_lower_case=args.do_lower_case)
        logger.info("checkpoint path: %s" % checkpoint)
        log_fp.write("checkpoint path: %s\n" % checkpoint)
        model = model_class.from_pretrained(checkpoint, args=args)
        model.to(args.device)
        result = test(args, model, parse_row_func, batch_data_func, prefix=prefix, log_fp=log_fp)
        result = dict(("evaluation_" + k + "_{}".format(global_step), v) for k, v in result.items())
        logger.info(json.dumps(result, ensure_ascii=False))
        log_fp.write(json.dumps(result, ensure_ascii=False) + "\n")
    log_fp.close()


if __name__ == "__main__":
    main()



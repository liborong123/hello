#!/usr/bin/env python
# encoding: utf-8
'''
@author: Hey
@email: sanyuan.**@**.com
@tel: 137****6540
@datetime: 2022/11/28 19:31
@project: LucaPCycle
@file: utils
@desc: utils
'''
import os
import math
import requests
import subprocess
import torch
import numpy as np
import sys, random
from sklearn.metrics import confusion_matrix
import matplotlib.pyplot as plt
import pynvml
from collections import OrderedDict

plt.rcParams.update({'font.size': 18})
plt.rcParams['axes.unicode_minus'] = False
sys.path.append(".")
sys.path.append("..")
sys.path.append("../src")
try:
    from file_operator import file_reader
    from common.multi_label_metrics import prob_2_pred, relevant_indexes, metrics_multi_label
    from common.metrics import metrics_multi_class, metrics_binary, metrics_regression
except ImportError:
    from src.file_operator import file_reader
    from src.common.multi_label_metrics import prob_2_pred, relevant_indexes, metrics_multi_label
    from src.common.metrics import metrics_multi_class, metrics_binary, metrics_regression

# not {'O', 'U', 'Z', 'J', 'B'}
# Common amino acids
common_amino_acid_set = {'R', 'X', 'S', 'G', 'W', 'I', 'Q', 'A', 'T', 'V', 'K', 'Y', 'C', 'N', 'L', 'F', 'D', 'M', 'P', 'H', 'E'}


def to_device(device, batch):
    '''
    input to device
    :param device:
    :param batch:
    :return:
    '''
    new_batch = {}
    sample_num = 0
    tens = None
    for item1 in batch.items():
        new_batch[item1[0]] = {}
        if isinstance(item1[1], dict):
            for item2 in item1[1].items():
                new_batch[item1[0]][item2[0]] = {}
                if isinstance(item2[1], dict):
                    for item3 in item2[1].items():
                        if item3[1] is not None and not isinstance(item3[1], int) and not isinstance(item3[1], str) and not isinstance(item3[1], float):
                            new_batch[item1[0]][item2[0]][item3[0]] = item3[1].to(device)
                            tens = item3[1]
                        else:
                            new_batch[item1[0]][item2[0]][item3[0]] = item3[1]
                else:
                    if item2[1] is not None and not isinstance(item2[1], int) and not isinstance(item2[1], str) and not isinstance(item2[1], float):
                        new_batch[item1[0]][item2[0]] = item2[1].to(device)
                        tens = item2[1]
                    else:
                        new_batch[item1[0]][item2[0]] = item2[1]
        else:
            if item1[1] is not None and not isinstance(item1[1], int) and not isinstance(item1[1], str) and not isinstance(item1[1], float):
                new_batch[item1[0]] = item1[1].to(device)
                tens = item1[1]
            else:
                new_batch[item1[0]] = item1[1]
    if tens is not None:
        sample_num = tens.shape[0]
    return new_batch, sample_num


def get_parameter_number(model):
    '''
    colc the parameter number of the model
    :param model: 
    :return: 
    '''
    param_size = 0
    param_sum = 0
    trainable_size = 0
    trainable_num = 0
    for param in model.parameters():
        cur_size = param.nelement() * param.element_size()
        cur_num = param.nelement()
        param_size += cur_size
        param_sum += cur_num
        if param.requires_grad:
            trainable_size += cur_size
            trainable_num += cur_num
    buffer_size = 0
    buffer_sum = 0
    for buffer in model.buffers():
        buffer_size += buffer.nelement() * buffer.element_size()
        buffer_sum += buffer.nelement()
    '''
    total_num = sum(p.numel() for p in model.parameters())
    total_size = sum(p.numel() * p.element_size() for p in model.parameters())
    total_num += sum(p.numel() for p in model.buffers())
    total_size += sum(p.numel() * p.element_size() for p in model.buffers())
    trainable_num = sum(p.numel() for p in model.parameters() if p.requires_grad)
    trainable_size = sum(p.numel() * p.element_size() for p in model.parameters() if p.requires_grad)
    '''
    return {
        'total_num': "%fM" % round((buffer_sum + param_sum)/(1024 * 1024), 2),
        'total_size': "%fMB" % round((buffer_size + param_size)/(1024 * 1024), 2),
        'param_sum': "%fM" % round(param_sum/(1024 * 1024), 2),
        'param_size': "%fMB" % round(param_size/(1024 * 1024), 2),
        'buffer_sum': "%fM" % round(buffer_sum/(1024 * 1024), 2),
        'buffer_size': "%fMB" % round(buffer_size/(1024 * 1024), 2),
        'trainable_num': "%fM" % round(trainable_num/(1024 * 1024), 2),
        'trainable_size': "%fMB" % round(trainable_size/(1024 * 1024), 2)
    }


def set_seed(args):
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.n_gpu > 0:
        torch.cuda.manual_seed(args.seed)
        torch.cuda.manual_seed_all(args.seed)


def label_id_2_label_name(output_mode, label_list, prob, threshold=0.5):
    '''
    convect label id to label name
    :param output_mode:
    :param label_list:
    :param prob:
    :param threshold:
    :return:
    '''
    if output_mode in ["multi-label", "multi_label"]:
        res = []
        pred = prob_2_pred(prob, threshold)
        pred_index = relevant_indexes(pred)
        for row in range(prob.shape[0]):
            label_names = [label_list[idx] for idx in pred_index[row]]
            res.append(label_names)
        return res
    elif output_mode in ["multi-class", "multi_class"]:
        pred = np.argmax(prob, axis=1)
        label_names = [label_list[idx] for idx in pred]
        return label_names
    elif output_mode in ["binary-class", "binary_class"]:
        if prob.ndim == 2:
            prob = prob.flatten(order="C")
        pred = prob_2_pred(prob, threshold)
        label_names = [label_list[idx] for idx in pred]
        return label_names
    else:
        raise KeyError(output_mode)


def plot_bins(data, xlabel, ylabel, bins, filepath):
    '''
    plot bins
    :param data:
    :param xlabel:
    :param ylabel:
    :param bins: bins number
    :param filepath: png save filepath
    :return:
    '''
    plt.figure(figsize=(40, 20), dpi=100)
    plt.hist(data, bins=bins)
    # plt.xticks(range(min(data), max(data)))
    # plt.grid(linestyle='--', alpha=0.5)

    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    if filepath is None:
        plt.show()
    else:
        plt.savefig(filepath)
        plt.clf()
    plt.close()


def plot_confusion_matrix_for_binary_class(targets, preds, cm=None, savepath=None):
    '''
    :param targets: ground truth
    :param preds: prediction probs
    :param cm: confusion matrix
    :param savepath: confusion matrix picture savepth
    '''

    plt.figure(figsize=(40, 20), dpi=100)
    if cm is None:
        cm = confusion_matrix(targets, preds, labels=[0, 1])

    plt.matshow(cm, cmap=plt.cm.Oranges)
    plt.colorbar()

    for x in range(len(cm)):
        for y in range(len(cm)):
            plt.annotate(cm[x, y], xy=(y, x), verticalalignment='center', horizontalalignment='center')
    plt.ylabel('True')
    plt.xlabel('Prediction')
    if savepath:
        plt.savefig(savepath, dpi=100)
    else:
        plt.show()
    plt.close("all")


def save_labels(filepath, label_list):
    '''
    save labels
    :param filepath:
    :param label_list:
    :return:
    '''
    with open(filepath, "w") as wfp:
        wfp.write("label" + "\n")
        for label in label_list:
            wfp.write(label + "\n")


def load_labels(filepath, header=True):
    '''
    load labels
    :param filepath:
    :param header: where the file has header or not
    :return:
    '''
    label_list = []
    with open(filepath, "r") as rfp:
        for label in rfp:
            label_list.append(label.strip())
    if len(label_list) > 0 and (header or label_list[0] == "label"):
        return label_list[1:]
    return label_list


def load_vocab(vocab_path):
    '''
    load vocab
    :param vocab_path:
    :return:
    '''
    vocab = {}
    with open(vocab_path, "r") as rfp:
        for line in rfp:
            v = line.strip()
            vocab[v] = len(vocab)
    return vocab


def subprocess_popen(statement):
    '''
    execute shell cmd
    :param statement:
    :return:
    '''
    p = subprocess.Popen(statement, shell=True, stdout=subprocess.PIPE)
    while p.poll() is None:
        if p.wait() != 0:
            print("fail.")
            return False
        else:
            re = p.stdout.readlines()
            result = []
            for i in range(len(re)):
                res = re[i].decode('utf-8').strip('\r\n')
                result.append(res)
            return result


def prepare_inputs(input_type, embedding_type, batch):
    if input_type == "sequence":
        inputs = {
            "input_ids_a": batch[0],
            "attention_mask_a": batch[1],
            "token_type_ids_a": batch[2],
            "input_ids_b": batch[4],
            "attention_mask_b": batch[5],
            "token_type_ids_b": batch[6],
            "labels": batch[-1]
        }
    elif input_type == "embedding":
        if embedding_type not in ["vector", "bos"]:
            inputs = {
                "embedding_info_a": batch[0],
                "embedding_attention_mask_a": batch[1],
                "embedding_info_b": batch[2],
                "embedding_attention_mask_b": batch[3],
                "labels": batch[-1]
            }
        else:
            inputs = {
                "embedding_info_a": batch[0],
                "embedding_attention_mask_a": None,
                "embedding_info_b": batch[1],
                "embedding_attention_mask_b": None,
                "labels": batch[-1]
            }
    elif input_type == "structure":
        inputs = {
            "struct_input_ids_a": batch[0],
            "struct_contact_map_a": batch[1],
            "struct_input_ids_b": batch[2],
            "struct_contact_map_b": batch[3],
            "labels": batch[-1]
        }
    elif input_type == "sefn":
        if embedding_type not in ["vector", "bos"]:
            inputs = {
                "input_ids_a": batch[0],
                "attention_mask_a": batch[1],
                "token_type_ids_a": batch[2],
                "embedding_info_a": batch[4],
                "embedding_attention_mask_a": batch[5],
                "input_ids_b": batch[6],
                "attention_mask_b": batch[7],
                "token_type_ids_b": batch[8],
                "embedding_info_b": batch[10],
                "embedding_attention_mask_b": batch[11],
                "labels": batch[-1],
            }
        else:
            inputs = {
                "input_ids_a": batch[0],
                "attention_mask_a": batch[1],
                "token_type_ids_a": batch[2],
                "embedding_info_a": batch[4],
                "embedding_attention_mask_a": None,
                "input_ids_b": batch[5],
                "attention_mask_b": batch[6],
                "token_type_ids_b": batch[7],
                "embedding_info_b": batch[9],
                "embedding_attention_mask_b": None,
                "labels": batch[-1],
            }
    elif input_type == "ssfn":
        inputs = {
            "input_ids_a": batch[0],
            "attention_mask_a": batch[1],
            "token_type_ids_a": batch[2],
            "struct_input_ids_a": batch[4],
            "struct_contact_map_a": batch[5],
            "input_ids_b": batch[6],
            "attention_mask_b": batch[7],
            "token_type_ids_b": batch[8],
            "struct_input_ids_b": batch[10],
            "struct_contact_map_b": batch[11],
            "labels": batch[-1]
        }
    else:
        inputs = None
    return inputs


def gene_seq_replace_re(seq):
    '''
    Nucleic acid 还原
    :param seq:
    :return:
    '''
    new_seq = ""
    for ch in seq:
        if ch == '1':
            new_seq += "A"
        elif ch == '2':
            new_seq += "T"
        elif ch == '3':
            new_seq += "C"
        elif ch == '4':
            new_seq += "G"
        else: # unknown
            new_seq += "N"
    return new_seq


def gene_seq_replace(seq):
    '''
    Nucleic acid （gene replace: A->1, U/T->2, C->3, G->4, N->5
    :param seq:
    :return:
    '''
    new_seq = ""
    for ch in seq:
        if ch in ["A", "a"]:
            new_seq += "1"
        elif ch in ["T", "U", "t", "u"]:
            new_seq += "2"
        elif ch in ["C", "c"]:
            new_seq += "3"
        elif ch in ["G", "g"]:
            new_seq += "4"
        else: # unknown
            new_seq += "5"
    return new_seq


def get_labels(label_filepath, header=True):
    '''
    get labels from file, exists header
    :param label_filepath:
    :param header:
    :return:
    '''
    with open(label_filepath, "r") as fp:
        labels = []
        multi_cols = False
        cnt = 0
        for line in fp:
            line = line.strip()
            cnt += 1
            if cnt == 1 and (header or line == "label"):
                if line.find(",") > 0:
                    multi_cols = True
                continue
            if multi_cols:
                idx = line.find(",")
                if idx > 0:
                    label_name = line[idx + 1:].strip()
                else:
                    label_name = line
            else:
                label_name = line
            labels.append(label_name)
        return labels


def available_gpu_id():
    '''
    计算可用的GPU id
    :return:
    '''
    pynvml.nvmlInit()
    if not torch.cuda.is_available():
        print("GPU not available")
        return -1
    # 获取GPU数量
    device_count = pynvml.nvmlDeviceGetCount()
    max_available_gpu = -1
    max_available_rate = 0

    # 遍历所有GPU并检查可用性
    for i in range(device_count):
        handle = pynvml.nvmlDeviceGetHandleByIndex(i)
        memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        utilization = pynvml.nvmlDeviceGetUtilizationRates(handle)
        # 假设如果GPU利用率小于某个阈值（例如10%），我们认为这个GPU目前是空闲的
        if utilization.gpu < 10 and max_available_rate < 100 - utilization.gpu:
            max_available_rate = 100 - utilization.gpu
            max_available_gpu = i
    # 打印可用的GPU ID
    if max_available_gpu > -1:
        print("Available GPU ID: %d, Free Rate: %0.2f%%" % (max_available_gpu, max_available_rate))
    else:
        print("No Available GPU!")

    # Shutdown NVML
    pynvml.nvmlShutdown()
    return max_available_gpu


def eval_metrics(output_mode, truths, preds, threshold=0.5):
    '''
    eval metrics
    :param output_mode:
    :param truths:
    :param preds:
    :param threshold:
    :return:
    '''
    print("\ntruths size: ", truths.shape)
    print("\npreds size: ", preds.shape)
    if output_mode in ["multi-label", "multi_label"]:
        return metrics_multi_label(truths, preds, threshold=threshold)
    elif output_mode in ["multi-class", "multi_class"]:
        return metrics_multi_class(truths, preds)
    elif output_mode == "regression":
        return metrics_regression(truths, preds)
    elif output_mode in ["binary-class", "binary_class"]:
        return metrics_binary(truths, preds, threshold=threshold)
    else:
        raise Exception("Not Support this output mode: %s" % output_mode)


def load_trained_model(model_config, args, model_class, model_dirpath):
    # load exists checkpoint
    print("load pretrained model: %s" % model_dirpath)
    try:
        model = model_class.from_pretrained(model_dirpath, args=args)
    except Exception as e:
        model = model_class(model_config, args=args)
        pretrained_net_dict = torch.load(os.path.join(model_dirpath, "pytorch.pth"),
                                         map_location=torch.device("cpu"))
        model_state_dict_keys = set()
        for key in model.state_dict():
            model_state_dict_keys.add(key)
        new_state_dict = OrderedDict()
        for k, v in pretrained_net_dict.items():
            if k.startswith("module."):
                # remove `module.`
                name = k[7:]
            else:
                name = k
            if name in model_state_dict_keys:
                new_state_dict[name] = v
        print("diff:")
        print(model_state_dict_keys.difference(new_state_dict.keys()))
        model.load_state_dict(new_state_dict)
    return model


def clean_seq(protein_id, seq, return_rm_index=False):
    seq = seq.upper()
    new_seq = ""
    has_invalid_char = False
    invalid_char_set = set()
    return_rm_index_set = set()
    for idx, ch in enumerate(seq):
        if 'A' <= ch <= 'Z' and ch not in ['J']:
            new_seq += ch
        else:
            invalid_char_set.add(ch)
            return_rm_index_set.add(idx)
            has_invalid_char = True
    if has_invalid_char:
        print("id: %s. Seq: %s" % (protein_id, seq))
        print("invalid char set:", invalid_char_set)
        print("return_rm_index:", return_rm_index_set)
    if return_rm_index:
        return new_seq, return_rm_index_set
    return new_seq


def sample_size(data_dirpath):
    if os.path.isdir(data_dirpath):
        new_filepaths = []
        for filename in os.listdir(data_dirpath):
            if not filename.startswith("."):
                new_filepaths.append(os.path.join(data_dirpath, filename))
        filepaths = new_filepaths
    else:
        filepaths = [data_dirpath]
    total = 0
    for filepath in filepaths:
        header = filepath.endswith(".tsv") or filepath.endswith(".csv")
        print("sample_size filepath: %s" % filepath)
        for _ in file_reader(filepath, header=header, header_filter=True):
            total += 1
    return total


def writer_info_tb(tb_writer, logs, global_step, prefix=None):
    '''
    write info to tensorboard
    :param tb_writer:
    :param logs:
    :param global_step:
    :param prefix:
    :return:
    '''
    if prefix is None:
        prefix = ""
    elif prefix != "":
        prefix = prefix + "_"
    for key, value in logs.items():
        if isinstance(value, dict):
            writer_info_tb(tb_writer, value, global_step, prefix=prefix + key)
        elif isinstance(value, list):
            print("writer_info_tb List, Key-Value: %s=%s" % (key, str(value)))
        elif not math.isnan(value) and not math.isinf(value):
            try:
                tb_writer.add_scalar(prefix + key, value, global_step)
            except Exception as e:
                print(e)
        else:
            print("writer_info_tb NaN or Inf, Key-Value: %s=%s" % (key, value))


def get_lr(optimizer):
    '''
    get learning rate
    :param optimizer:
    :return:
    '''
    for p in optimizer.param_groups:
        if "lr" in p:
            return p["lr"]


def metrics_merge(results, all_results):
    '''
    merge metrics
    :param results:
    :param all_results:
    :return:
    '''
    for item1 in results.items():
        if item1[0] not in all_results:
            all_results[item1[0]] = {}
        for item2 in item1[1].items():
            if item2[0] not in all_results[item1[0]]:
                all_results[item1[0]][item2[0]] = {}
            for item3 in item2[1].items():
                if item3[0] not in all_results[item1[0]][item2[0]]:
                    all_results[item1[0]][item2[0]][item3[0]] = item3[1]
                else:
                    all_results[item1[0]][item2[0]][item3[0]] += item3[1]
    return all_results


def print_shape(item):
    '''
    print shape
    :param item:
    :return:
    '''
    if isinstance(item, dict):
        for item1 in item.items():
            print(item1[0] + ":")
            print_shape(item1[1])
    elif isinstance(item, list):
        for idx, item1 in enumerate(item):
            print("idx: %d" % idx)
            print_shape(item1)
    else:
        print("shape:", item.shape)


def process_outputs(output_mode, truth, pred, output_truth, output_pred, ignore_index, keep_seq=False):
    if keep_seq:
        # to do
        return None, None
    else:
        if output_mode in ["multi_class", "multi-class"]:
            cur_truth = truth.view(-1)
            cur_mask = cur_truth != ignore_index
            cur_pred = pred.view(-1, pred.shape[-1])
            cur_truth = cur_truth[cur_mask]
            cur_pred = cur_pred[cur_mask, :]
            sum_v = cur_mask.sum().item()
        elif output_mode in ["multi_label", "multi-label"]:
            cur_truth = truth.view(-1, truth.shape[-1])
            cur_pred = pred.view(-1, pred.shape[-1])
            sum_v = pred.shape[0]
        elif output_mode in ["binary_class", "binary-class"]:
            cur_truth = truth.view(-1)
            cur_mask = cur_truth != ignore_index
            cur_pred = pred.view(-1)
            cur_truth = cur_truth[cur_mask]
            cur_pred = cur_pred[cur_mask]
            sum_v = cur_mask.sum().item()
        elif output_mode in ["regression"]:
            cur_truth = truth.view(-1)
            cur_mask = cur_truth != ignore_index
            cur_pred = pred.view(-1)
            cur_truth = cur_truth[cur_mask]
            cur_pred = cur_pred[cur_mask]
            sum_v = cur_mask.sum().item()
        else:
            raise Exception("not output mode: %s" % output_mode)
        if sum_v > 0:
            cur_truth = cur_truth.detach().cpu().numpy()
            cur_pred = cur_pred.detach().cpu().numpy()
            if output_truth is None or output_pred is None:
                return cur_truth, cur_pred
            else:
                output_truth = np.append(output_truth, cur_truth,  axis=0)
                output_pred = np.append(output_pred, cur_pred,  axis=0)
                return output_truth, output_pred
    return truth, pred


def print_batch(value, key=None, debug_path=None, wfp=None, local_rank=-1):
    '''
    print a batch
    :param value:
    :param key:
    :param debug_path:
    :param wfp:
    :param local_rank:
    :return:
    '''
    if isinstance(value, list):
        for idx, v in enumerate(value):
            if wfp is not None:
                if v is not None:
                    wfp.write(str([torch.min(v), torch.min(torch.where(v == -100, 10000, v)), torch.max(v)]) + "\n")
                    wfp.write(str(v.shape) + "\n")
                else:
                    wfp.write("None\n")
                wfp.write("-" * 10 + "\n")
            else:
                if v is not None:
                    print([torch.min(v), torch.min(torch.where(v == -100, 10000, v)), torch.max(v)])
                    print(v.shape)
                else:
                    print("None")
                print("-" * 50)
            if v is not None:
                try:
                    value = v.detach().cpu().numpy().astype(int)
                    if debug_path is not None:
                        if value.ndim == 3:
                            for dim_1_idx in range(value.shape[0]):
                                np.savetxt(os.path.join(debug_path, "%s_batch_%d.txt" % (key, dim_1_idx)), value[dim_1_idx, :, :], fmt='%i', delimiter=",")
                        else:
                            np.savetxt(os.path.join(debug_path, "%d.txt" % idx), value, fmt='%i', delimiter=",")
                    else:
                        if value.ndim == 3:
                            for dim_1_idx in range(value.shape[0]):
                                np.savetxt(os.path.join(debug_path, "%s_batch_%d.txt" % (key, dim_1_idx)), value[dim_1_idx, :, :], fmt='%i', delimiter=",")
                        else:
                            np.savetxt("%d.txt" % idx, value, fmt='%i', delimiter=",")
                except Exception as e:
                    print(e)
    elif isinstance(value, dict):
        for item in value.items():
            if wfp is not None:
                wfp.write(str(item[0]) + ":\n")
            else:
                print(str(item[0]) + ':')
            print_batch(item[1], item[0], debug_path, wfp, local_rank)
    else:
        if wfp is not None:
            if value is not None:
                wfp.write(str([torch.min(value), torch.min(torch.where(value == -100, 10000, value)), torch.max(value)]) + "\n")
                wfp.write(str(value.shape) + "\n")
            else:
                wfp.write("None\n")
            wfp.write("-" * 10 + "\n")
        else:
            if value is not None:
                print([torch.min(value), torch.min(torch.where(value == -100, 10000, value)), torch.max(value)])
                print(value.shape)
            else:
                print("None")
            print("-" * 10)
        if value is not None:
            if key != "prot_structure":
                fmt = '%i'
                d_type = int
            else:
                fmt = '%0.4f'
                d_type = float
            try:
                value = value.detach().cpu().numpy().astype(d_type)
                if debug_path is not None:
                    if value.ndim == 3:
                        for dim_1_idx in range(value.shape[0]):
                            np.savetxt(os.path.join(debug_path, "%s_batch_%d.txt" % (key, dim_1_idx)), value[dim_1_idx, :, :], fmt=fmt, delimiter=",")
                    else:
                        np.savetxt(os.path.join(debug_path, "%s.txt" % key), value, fmt=fmt, delimiter=",")
                else:
                    if value.ndim == 3:
                        for dim_1_idx in range(value.shape[0]):
                            np.savetxt("%s_batch_%d.txt" % (key, dim_1_idx), value[dim_1_idx, :, :], fmt=fmt, delimiter=",")
                    else:
                        np.savetxt("%s.txt" % key, value, fmt=fmt, delimiter=",")
            except Exception as e:
                print(e)


def gcd(x, y):
    '''
    最大公约数
    :param x:
    :param y:
    :return:
    '''
    m = max(x, y)
    n = min(x, y)
    while m % n:
        m, n = n, m % n
    return n


def lcm(x, y):
    '''
    最小公倍数
    :param x:
    :param y:
    :return:
    '''
    m = max(x, y)
    n = min(x, y)
    while m % n:
        m, n = n, m % n
    return x*y//n


def calc_emb_filename_by_seq_id(seq_id, embedding_type):
    """
    根据seq_id得到emb_filename
    :param seq_id:
    :param embedding_type:
    :return:
    """
    seq_id = str(seq_id)
    if seq_id[0] == ">":
        seq_id = seq_id[1:]
    if "|" in seq_id:
        strs = seq_id.split("|")
        if len(strs) > 1:
            emb_filename = embedding_type + "_" + strs[1].strip() + ".pt"
        else:
            emb_filename = embedding_type + "_" + seq_id.replace(" ", "").replace("/", "_") + ".pt"
    else:
        emb_filename = embedding_type + "_" + seq_id.replace(" ", "").replace("/", "_") + ".pt"
    return emb_filename


def download_file(url, local_filename):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        dir_name = os.path.dirname(local_filename)
        if not os.path.exists(dir_name):
            os.makedirs(dir_name)
        with open(local_filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk: # filter out keep-alive new chunks
                    f.write(chunk)
    return local_filename


def download_folder(base_url, file_names, local_dir):
    if not os.path.exists(local_dir):
        os.makedirs(local_dir)

    for file_name in file_names:
        file_url = f"{base_url}/{file_name}"
        local_filename = os.path.join(local_dir, file_name)
        download_file(file_url, local_filename)
        print(f"Downloaded {file_name}")


def download_trained_checkpoint_lucapcycle(
        model_dir,
        model_dataset_name=["extra_p_2_class_v2", "extra_p_31_class_v2"],
        model_dataset_type=["protein", "protein"],
        model_task_type=["binary_class", "multi_class"],
        model_type=["lucaprot", "lucaprot"],
        model_input_type=["seq_matrix", "seq_matrix"],
        model_time_str=["20240120061735", "20240120061524"],
        model_step=["955872", "294536"],
        base_url="http://47.93.21.181/lucapcycle/TrainedCheckPoint"
):
    try:
        download_trained_checkpoint_vocab_subword(model_dir=model_dir, model_dataset_name=model_dataset_name)
        logs_file_names = ["logs.txt", "label.txt"]
        models_file_names = ["config.json", "pytorch_model.bin", "training_args.bin",
                             "tokenizer/special_tokens_map.json", "tokenizer/tokenizer_config.json", "tokenizer/vocab.txt"]
        for model_idx in range(len(model_time_str)):
            logs_path = "logs/%s/%s/%s/%s/%s/%s" % (
                model_dataset_name[model_idx],
                model_dataset_type[model_idx],
                model_task_type[model_idx],
                model_type[model_idx],
                model_input_type[model_idx],
                model_time_str[model_idx]
            )
            models_path = "models/%s/%s/%s/%s/%s/%s/checkpoint-step%s" % (
                model_dataset_name[model_idx],
                model_dataset_type[model_idx],
                model_task_type[model_idx],
                model_type[model_idx],
                model_input_type[model_idx],
                model_time_str[model_idx],
                model_step[model_idx]
            )
            logs_local_dir = os.path.join(model_dir, logs_path)
            exists = True
            for logs_file_name in logs_file_names:
                if not os.path.exists(os.path.join(logs_local_dir, logs_file_name)):
                    exists = False
                    break
            models_local_dir = os.path.join(model_dir, models_path)
            if exists:
                for models_file_name in models_file_names:
                    if not os.path.exists(os.path.join(models_local_dir, models_file_name)):
                        exists = False
                        break
            if not exists:
                print("*" * 20 + "Downloading" + "*" * 20)
                print("Downloading LucaPCycle TrainedCheckPoint: LucaPCycle-%s-%s-%s-%s ..." %
                      (
                          model_dataset_name[model_idx],
                          model_task_type[model_idx],
                          model_time_str[model_idx],
                          model_step[model_idx]
                      )
                )
                print("Wait a moment, please.")
                # download logs
                if not os.path.exists(logs_local_dir):
                    os.makedirs(logs_local_dir)
                logs_base_url = os.path.join(base_url, logs_path)
                download_folder(logs_base_url, logs_file_names, logs_local_dir)
                # download models
                if not os.path.exists(models_local_dir):
                    os.makedirs(models_local_dir)
                models_base_url = os.path.join(base_url, models_path)
                download_folder(models_base_url, models_file_names, models_local_dir)
                print("LucaPCycle Downloaded.")
                print("*" * 50)
    except Exception as e:
        print(e)
        print("Download automatically LucaPCycle Trained CheckPoint failed!")
        print("You can manually download 'logs/' and 'models/' into the project: %s/ from %s" % (os.path.abspath(model_dir),
                                                                                                 os.path.join(base_url, "TrainedCheckPoint/")
                                                                                                 )
        )
        raise Exception(e)


def download_trained_checkpoint_vocab_subword(
        model_dir,
        model_dataset_name=["extra_p_2_class_v2", "extra_p_31_class_v2"],
        base_url="http://47.93.21.181/lucapcycle/LucaPCycleV2/"
):
    try:
        vocab_dir = "vocab/"
        vocab_file_names = ["extra_p_50_subword_vocab_20000.txt", "extra_p_31_class_subword_vocab_20000.txt"]
        subword_dir = "subword/"
        subword_file_names = ["extra_p_50_codes_20000.txt", "extra_p_31_class_codes_20000.txt"]
        for model_idx in range(len(model_dataset_name)):
            vocab_filepath = os.path.join(vocab_dir, model_dataset_name[model_idx], vocab_file_names[model_idx])
            vocab_local_filepath = os.path.join(model_dir, vocab_filepath)
            exists = True
            if not os.path.exists(vocab_local_filepath):
                exists = False
            subword_filepath = os.path.join(subword_dir, model_dataset_name[model_idx], subword_file_names[model_idx])
            subword_local_filepath = os.path.join(model_dir, subword_filepath)
            if not os.path.exists(subword_local_filepath):
                exists = False
            if not exists:
                print("*" * 20 + "Downloading" + "*" * 20)
                print("Downloading LucaPCycle Vocab & Subword: LucaPCycle-%s ..." % model_dataset_name[model_idx])
                print("Wait a moment, please.")
                # download logs
                if not os.path.exists(os.path.dirname(vocab_local_filepath)):
                    os.makedirs(os.path.dirname(vocab_local_filepath))
                vocab_base_url = os.path.join(base_url, vocab_filepath)
                download_file(vocab_base_url, vocab_local_filepath)
                # download subword
                if not os.path.exists(os.path.dirname(subword_local_filepath)):
                    os.makedirs(os.path.dirname(subword_local_filepath))
                subword_base_url = os.path.join(base_url, subword_filepath)
                download_file(subword_base_url, subword_local_filepath)
                print("LucaPCycle Vocab & Subword Downloaded.")
                print("*" * 50)
    except Exception as e:
        print(e)
        print("Download automatically LucaPCycle Vocab & Subword failed!")
        print("You can manually download 'vocab/' and 'subword/' into the project: %s/ from %s" % (os.path.abspath(model_dir), os.path.join(base_url, "LucaPCycle/")))
        raise Exception(e)
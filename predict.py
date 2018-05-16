"""
Predict the labels
"""
import argparse
import numpy as np
import tensorflow as tf
import importlib
import os
import json
import models.model as MODEL
import utils.pc_util as pc_util

# Parser

parser = argparse.ArgumentParser()
parser.add_argument('--gpu', type=int, default=0, help='GPU to use [default: GPU 0]')
parser.add_argument('--n', type=int, default=8, help='Number of scenes you want [default : 1]')
parser.add_argument('--ckpt', default='', help='Checkpoint file')
parser.add_argument('--num_point', type=int, default=8192, help='Point Number [default: 8192]')
parser.add_argument('--set', default="train", help='train or test [default: train]')
parser.add_argument('--batch_size', type=int, default=1, help='Batch size [default: 1]') # LET DEFAULT FOR THE MOMENT!
parser.add_argument('--dataset', default='semantic', help='Dataset [default: semantic]')
parser.add_argument('--config', type=str, default="config.json", metavar='N', help='config file')
FLAGS = parser.parse_args()

JSON_DATA_CUSTOM = open(FLAGS.config).read()
CUSTOM = json.loads(JSON_DATA_CUSTOM)
JSON_DATA = open('default.json').read()
PARAMS = json.loads(JSON_DATA)
PARAMS.update(CUSTOM)

CHECKPOINT = FLAGS.ckpt
GPU_INDEX = FLAGS.gpu
NUM_POINT = FLAGS.num_point
SET = FLAGS.set
BATCH_SIZE = FLAGS.batch_size
DATASET_NAME = FLAGS.dataset
NSCENES = FLAGS.n

DROPOUT = False
DROPOUT_RATIO = 0.875
AUGMENT = False

if DROPOUT:
    print("dropout is on, with ratio %f" %(DROPOUT_RATIO))
if AUGMENT:
    print ("rotation is on")

# Import dataset
data = importlib.import_module('dataset.' + DATASET_NAME)
DATASET = data.Dataset(npoints=NUM_POINT, split=SET, box_size=PARAMS['box_size'], use_color=PARAMS['use_color'],
                             dropout_max=PARAMS['input_dropout'], path=PARAMS['data_path'], accept_rate=PARAMS['accept_rate'])
NUM_CLASSES = DATASET.num_classes

LABELS_TEXT = DATASET.labels_names

# Outputs

OUTPUT_DIR = os.path.join("visu", DATASET_NAME+"_"+SET)
if not os.path.exists("visu"): os.mkdir("visu")
if not os.path.exists(OUTPUT_DIR): os.mkdir(OUTPUT_DIR)
    
OUTPUT_DIR_GROUNDTRUTH = os.path.join(OUTPUT_DIR, "scenes_groundtruth_test")
OUTPUT_DIR_PREDICTION = os.path.join(OUTPUT_DIR, "scenes_predictions_test")

if not os.path.exists(OUTPUT_DIR_GROUNDTRUTH): os.mkdir(OUTPUT_DIR_GROUNDTRUTH)
if not os.path.exists(OUTPUT_DIR_PREDICTION): os.mkdir(OUTPUT_DIR_PREDICTION)


def predict():
    """
    Load the selected checkpoint and predict the labels
    Write in the output directories both groundtruth and prediction
    This enable to visualize side to side the prediction and the true labels,
    and helps to debug the network
    """
    with tf.device('/gpu:'+str(GPU_INDEX)):
        pointclouds_pl, labels_pl, _ = MODEL.placeholder_inputs(BATCH_SIZE, NUM_POINT, hyperparams=PARAMS)
        print (tf.shape(pointclouds_pl))
        is_training_pl = tf.placeholder(tf.bool, shape=())

        # simple model
        pred, _ = MODEL.get_model(pointclouds_pl, is_training_pl, NUM_CLASSES, hyperparams=PARAMS)
        
        # Add ops to save and restore all the variables.
        saver = tf.train.Saver()
        
    # Create a session
    config = tf.ConfigProto()
    config.gpu_options.allow_growth = True
    config.allow_soft_placement = True
    config.log_device_placement = False
    sess = tf.Session(config=config)

    # Restore variables from disk.
    saver.restore(sess, CHECKPOINT)
    print ("Model restored.")

    ops = {'pointclouds_pl': pointclouds_pl,
           'labels_pl': labels_pl,
           'is_training_pl': is_training_pl,
           'pred': pred}

    # To add the histograms
    meta_hist_true = np.zeros(9)
    meta_hist_pred = np.zeros(9)

    for idx in range(NSCENES):
        data, true_labels, _, _ = DATASET.next_input(DROPOUT, True, False)
        # Ground truth
        print ("Exporting scene number " + str(idx))
        pc_util.write_ply_color(data[:,0:3], true_labels, OUTPUT_DIR_GROUNDTRUTH+"/{}_{}.txt".format(SET, idx), NUM_CLASSES)

        # Prediction
        pred_labels = predict_one_input(sess, ops, data)

        # Compute mean IoU
        iou, update_op = tf.metrics.mean_iou(tf.to_int64(true_labels), tf.to_int64(pred_labels), NUM_CLASSES)
        sess.run(tf.local_variables_initializer())
        update_op.eval(session=sess)
        print(sess.run(iou))

        hist_true, _ = np.histogram(true_labels,range(NUM_CLASSES+1))
        hist_pred, _ = np.histogram(pred_labels,range(NUM_CLASSES+1))

        # update meta histograms
        meta_hist_true += hist_true
        meta_hist_pred += hist_pred

        # print individual histograms
        print (hist_true)
        print (hist_pred)
        
        pc_util.write_ply_color(data[:,0:3], pred_labels, "{}/{}_{}.txt".format(OUTPUT_DIR_PREDICTION,SET, idx), NUM_CLASSES)
    
    meta_hist_pred = (meta_hist_pred/sum(meta_hist_pred))*100
    meta_hist_true = (meta_hist_true/sum(meta_hist_true))*100
    print(LABELS_TEXT)
    print(meta_hist_true)
    print(meta_hist_pred)


def predict_one_input(sess, ops, data):
    is_training = False
    batch_data = np.array([data]) # 1 x NUM_POINT x 3
    feed_dict = {ops['pointclouds_pl']: batch_data,
                 ops['is_training_pl']: is_training}
    pred_val = sess.run([ops['pred']], feed_dict=feed_dict)
    pred_val = pred_val[0][0] # NUMPOINTSx9
    pred_val = np.argmax(pred_val,1)
    return pred_val


if __name__ == "__main__":
    print ('pid: %s'%(str(os.getpid())))
    with tf.Graph().as_default():
        predict()

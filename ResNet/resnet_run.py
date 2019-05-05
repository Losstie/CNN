#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
@project: CNN
@file:resnet_run.py.py
@author: losstie
@create_time: 2019/5/3 21:27
@description:main function Runs a ResNet model on the CIFAR-10 dataset
"""
from __future__ import absolute_import
from __future__ import  division
from __future__ import print_function

import os

from absl import app as absl_app
from absl import flags
import tensorflow as tf

import resnet_model

HEIGHT = 32
WIDTH = 32
NUM_CHANNELS = 3
_DEFAULT_IMAGE_BYTES = HEIGHT * WIDTH * NUM_CHANNELS

_RECORD_BYTES = _DEFAULT_IMAGE_BYTES + 1
NUM_CLASSES = 10
_NUM_DATA_FILES = 5

NUM_IMAGES = {
    'train': 48000,
    'validation': 12000,
}

DATASET_NAME = 'CIFAR-10'

#################################################
# Data processing
#################################################
def get_filenames(is_training, data_dir):
    """Returns a list of filenames."""
    assert tf.io.gfile.exists(data_dir), (
        'Run cifar-10_download_and_extract.py first to download and extract the'
        'CIFAR-10 data.')
    if is_training:
        return [os.path.join(data_dir,'data_batch_%d.bin' % i) for i in range(1, _NUM_DATA_FILES + 1)]
    else:
        return [os.path.join(data_dir, 'test_batch.bin')]


def parse_record(raw_record, is_training, dtype):
    """Parse CIFAR-10 image and label from a raw record."""
    # convert bytes to a vector of uint8 that is _RECORD_BYTES long
    record_vector = tf.io.decode_raw(raw_record, tf.uint8)

    # The first byte represents the label, which we convert from uint8 to int32
    # and then to one-hot
    label = tf.cast(record_vector[0], tf.int32)

    # The remaining bytes after the label represent the image, which we reshape
    # from [depth * height * width] to [depth, height, width].

    depth_major = tf.reshape(record_vector[1:_RECORD_BYTES],[NUM_CHANNELS, HEIGHT, WIDTH])

    # Convert from [depth, height, width] to [height, width, depth], and cast as
    # float32.

    image = tf.cast(tf.transpose(a=depth_major, perm=[1, 2, 0]), tf.float32)

    image = preprocess_image(image, is_training)
    image = tf.cast(image, dtype)

    return image, label


def preprocess_image(image, is_training):
    """Return a singel image of layout [height, width depth]"""
    if is_training:
        # Resize the image to add four extra pixels on each side.
        image = tf.image.resize_image_with_crop_or_pad(image, HEIGHT + 8, WIDTH + 8)

    # Randomly crop a [HEIGHT, WIDTH] section of the image
    image = tf.image.random_crop(image, [HEIGHT, WIDTH, NUM_CHANNELS])

    # Subtract off the mean and divide by the variance of the pixels.
    # Standardize pictures to accelerate the training of neural networks
    image = tf.image.per_image_standardization(image)
    return image

def input_fn(is_training, data_dir, batch_size, shuffle_buffer=NUM_IMAGES['train'],
             num_epochs=1, drop_remainder=False,dtype=tf.float32, parse_record_fn=parse_record):
    """Input function which provides batches for train or eval.
    Args:
        is_training: A boolean denoting whether the input is for training.
        data_dir: the directory containing the input data.
        batch_size: The number of samples per batch
        shuffle_buffer: The buffer size to use when shuffling records. A larger
            value results in better randomness, but smaller values reduce startup
            time and use less memory.
        num_epochs: The number of epochs to repeat the dataset.
        drop_remainder:  A boolean indicates whether to drop the remainder of the
                batches. If True, the batch dimension will be static.
        dtype: Data type to use for image/features
        parse_record_fn: Function to use for parsing the records.


    Returns:
        A dataset that can be used for iteration.
    """
    filenames = get_filenames(is_training, data_dir)
    dataset = tf.data.FixedLengthRecordDataset(filenames, _RECORD_BYTES)
    options = tf.data.Options()
    dataset = dataset.with_options(options)

    # Prefetches a batch at a time to smooth out the time taken to load latency
    dataset = dataset.prefetch(buffer_size=batch_size)
    if is_training:
        # shuffles records before repeating to respect epochs boundaries
        dataset = dataset.shuffle(buffer_size=shuffle_buffer)
    dataset = dataset.repeat(num_epochs)

    dataset = dataset.map(lambda value:parse_record_fn(value, is_training, dtype))
    dataset = dataset.batch(batch_size, drop_remainder=drop_remainder)



    # Operations between the final prefetch and the get_next call to the iterator
    # will happen synchronously during run time. We prefetch here again to
    # background all of the above processing work and keep it out of the
    # critical training path. Setting buffer_size to tf.contrib.data.AUTOTUNE
    # allows DistributionStrategies to adjust how many batches to fetch based
    # on how many devices are present.
    dataset = dataset.prefetch(buffer_size=tf.data.experimental.AUTOTUNE)

    print(dataset.output_shapes)

    return dataset



###############################################################################
# Running the model
###############################################################################
class Cifar10Model(resnet_model.Model):
    """Model class with appropriate defaults for CIFAR-10 data. """

    def __init__(self, resnet_size, num_classes=NUM_CLASSES,
                 resnet_version=resnet_model.DEFAULT_VERSION,
                 dtype=resnet_model.DEFAULT_DTYPE):
        """These are the parameters that work for `CIFAR-10` data
        Args:
            resnet_size: The number of convolution layers needed in the model.
            data_format: Either `channels_first` or `channels_last`, specifying which
                data format to use when setting up the model.
            num_classes: The number of output classes needed from the model. This enables
                users to extend the same model to their own datasets.
            resnet_version:Integer representing which version of the ResNet network to use.
                See ReadME for details. vaild values:[1, 2]
            dtype: The tensorflow dtype to use for calculations.
        Raise:
            ValueError: if invalid resnet_size is chosen
        """
        if resnet_size % 6 != 2:
            raise ValueError('resnet_size must be 6n+2:',resnet_size)

        num_blocks = (resnet_size - 2) // 6

        super(Cifar10Model, self).__init__(
            resnet_size=resnet_size,
            bottleneck=False,
            num_classes=num_classes,
            num_filters=16,
            kernel_size=3,
            conv_stride=1,
            first_pool_size=None,
            first_pool_stride=None,
            block_size=[num_blocks] * 3,
            block_stride=[1, 2, 2],
            resnet_version=resnet_version,
            dtype=dtype
        )


def resnet_main(flags_obj, model_function, input_function, dataset_name, shape=None):
    """Shared main loop for ResNet Models'

    Args:
        flags_obj: An object containing parsed flags. See define_resnet_flags() for details.
        model_function: the function that instantiates the Model and builds the
            ops for train/eval. This will be passed directly into the estimator.
        input_function: the function that processes the dataset and returns a
            dataset that the estimator can train on. This will be wrapped with
            all the relevant flags for running and passed to estimator.
        dataset_name: the name of the dataset for training and evaluation. This is
            used for logging purpose.
        shape: list of ints representing the shape of the images used for training.
            This is only used if flags_obj.export_dir is passed.
    """

    session_config = tf.compat.v1.ConfigProto(allow_soft_placement=True)

    run_config = tf.estimator.RunConfig(session_config=session_config,
                                        save_checkpoints_secs=60*60*24,
                                        save_checkpoints_steps=None)

    if flags_obj.pretrained_model_checkpoint_path is not None:
        warm_start_settings = tf.estimator.WarmStartSettings(
            flags_obj.pretrained_model_checkpoint_path,
            vars_to_warm_start='^(?!.*dense)')
    else:
        warm_start_settings =None

    classifier = tf.estimator.Estimator(
        model_fn=model_function, model_dir=flags_obj.model_dir, config=run_config,
        warm_start_from=warm_start_settings, params={
            'resnet_size':int(flags_obj.resnet_size),
            'batch_size':flags_obj.batch_size,
            'resnet_version':int(flags_obj.resnet_version),
            'loss_scale':1,
            'dtype':tf.float32,
            'fine_tune': flags_obj.fine_tune
        })

    def input_fn_train(num_epochs):
        return input_function(
            is_training=True,
            data_dir=flags_obj.data_dir,
            batch_size=flags_obj.batch_size,
            num_epochs=num_epochs,
            dtype=tf.float32)


    # def input_fn_eval():
    #     return input_function(
    #         is_training=False,
    #         data_dir=flags_obj.data_dir,
    #         batch_size=flags_obj.batch_size,
    #         num_epochs=1,
    #         dtype=tf.float32)

    classifier.train(input_fn=lambda : input_fn_train(num_epochs=20), steps=2000)




def resnet_model_fn(features, labels, mode, model_class, resnet_size,
                    weight_decay, learning_rate_fn, momentum,
                    resnet_version, loss_scale,loss_filter_fn=None, dtype=resnet_model.DEFAULT_DTYPE,
                    fine_tune=False,label_smoothing=0.0):
    """Shared functionality for different resnet model_fns

    Return:
       EstimatorSpec parameterized according to the input params and the
    current mode.
    """
    model = model_class(resnet_size, resnet_version=resnet_version,dtype=dtype)

    logits = model(features, mode == tf.estimator.ModeKeys.TRAIN)

    predictions = {
        'classes': tf.argmax(input=logits, axis=1),
        'probabilities': tf.nn.softmax(logits, name='softmax_tensor')
    }

    if mode == tf.estimator.ModeKeys.PREDICT:
        # Return the predictions and the specification for serving a SavedModel
        return tf.estimator.EstimatorSpec(
            mode=mode,
            predictions=predictions,
            export_outputs={
                'predict': tf.estimator.export.PredictOutput(predictions)
            })
        # Calculate loss, which includes softmax cross entropy and L2 regularization.
    if label_smoothing != 0.0:
        one_hot_labels = tf.one_hot(labels, 1001)
        cross_entropy = tf.losses.softmax_cross_entropy(
            logits=logits, onehot_labels=one_hot_labels,
            label_smoothing=label_smoothing)
    else:
        cross_entropy = tf.compat.v1.losses.sparse_softmax_cross_entropy(
            logits=logits, labels=labels)

        # Create a tensor named cross_entropy for logging purposes.
    tf.identity(cross_entropy, name='cross_entropy')
    tf.compat.v1.summary.scalar('cross_entropy', cross_entropy)

    # If no loss_filter_fn is passed, assume we want the default behavior,
    # which is that batch_normalization variables are excluded from loss.
    def exclude_batch_norm(name):
        return 'batch_normalization' not in name

    loss_filter_fn = loss_filter_fn or exclude_batch_norm

    # Add weight decay to the loss.
    l2_loss = weight_decay * tf.add_n(
        # loss is computed using fp32 for numerical stability.
        [
            tf.nn.l2_loss(tf.cast(v, tf.float32))
            for v in tf.compat.v1.trainable_variables()
            if loss_filter_fn(v.name)
        ])
    tf.compat.v1.summary.scalar('l2_loss', l2_loss)
    loss = cross_entropy + l2_loss

    if mode == tf.estimator.ModeKeys.TRAIN:
        global_step = tf.compat.v1.train.get_or_create_global_step()

        learning_rate = learning_rate_fn(global_step)

        # Create a tensor named learning_rate for logging purposes
        tf.identity(learning_rate, name='learning_rate')
        tf.compat.v1.summary.scalar('learning_rate', learning_rate)

        if flags.FLAGS.enable_lars:
            optimizer = tf.contrib.opt.LARSOptimizer(
                learning_rate,
                momentum=momentum,
                weight_decay=weight_decay,
                skip_list=['batch_normalization', 'bias'])
        else:
            optimizer = tf.compat.v1.train.MomentumOptimizer(
                learning_rate=learning_rate,
                momentum=momentum
            )



        def _dense_grad_filter(gvs):
            """Only apply gradient updates to the final layer.
            This function is used for fine tuning.
            Args:
              gvs: list of tuples with gradients and variable info
            Returns:
              filtered gradients so that only the dense layer remains
            """
            return [(g, v) for g, v in gvs if 'dense' in v.name]

        if loss_scale != 1 :
            # When computing fp16 gradients, often intermediate tensor values are
            # so small, they underflow to 0. To avoid this, we multiply the loss by
            # loss_scale to make these tensor values loss_scale times bigger.
            scaled_grad_vars = optimizer.compute_gradients(loss * loss_scale)

            if fine_tune:
                scaled_grad_vars = _dense_grad_filter(scaled_grad_vars)

            # Once the gradient computation is complete we can scale the gradients
            # back to the correct scale before passing them to the optimizer.
            unscaled_grad_vars = [(grad / loss_scale, var)
                                  for grad, var in scaled_grad_vars]
            minimize_op = optimizer.apply_gradients(unscaled_grad_vars, global_step)
        else:
            grad_vars = optimizer.compute_gradients(loss)
            if fine_tune:
                grad_vars = _dense_grad_filter(grad_vars)
            minimize_op = optimizer.apply_gradients(grad_vars, global_step)

        update_ops = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.UPDATE_OPS)
        train_op = tf.group(minimize_op, update_ops)
    else:
        train_op = None

    accuracy = tf.compat.v1.metrics.accuracy(labels, predictions['classes'])
    accuracy_top_5 = tf.compat.v1.metrics.mean(
        tf.nn.in_top_k(predictions=logits, targets=labels, k=5, name='top_5_op'))
    metrics = {'accuracy': accuracy,
               'accuracy_top_5': accuracy_top_5}

    # Create a tensor named train_accuracy for logging purposes
    tf.identity(accuracy[1], name='train_accuracy')
    tf.identity(accuracy_top_5[1], name='train_accuracy_top_5')
    tf.compat.v1.summary.scalar('train_accuracy', accuracy[1])
    tf.compat.v1.summary.scalar('train_accuracy_top_5', accuracy_top_5[1])

    return tf.estimator.EstimatorSpec(
        mode=mode,
        predictions=predictions,
        loss=loss,
        train_op=train_op,
        eval_metric_ops=metrics)


def learning_rate_with_decay(batch_size, batch_denom, num_images, boundary_epochs, decay_rates,
                             base_lr=0.1, warmup=False):
    """ Get a learning rate that decays steps-wise as taining progresses.

    """
    initial_learning_rate = base_lr * batch_size / batch_denom
    batches_per_epoch = num_images / batch_size

    # Reduce the learning rate at certain epochs.
    # CIFAR-10: divide by 10 at epoch 100, 150, and 200
    # ImageNet: divide by 10 at epoch 30, 60, 80, and 90
    boundaries = [int(batches_per_epoch * epoch) for epoch in boundary_epochs]
    vals = [initial_learning_rate * decay for decay in decay_rates]

    def learning_rate_fn(global_step):
        """Builds scaled learning rate function with 5 epoch warm up."""
        lr = tf.compat.v1.train.piecewise_constant(global_step, boundaries, vals)
        if warmup:
            warmup_steps = int(batches_per_epoch * 5)
            warmup_lr = (
                    initial_learning_rate * tf.cast(global_step, tf.float32) / tf.cast(
                warmup_steps, tf.float32))
            return tf.cond(pred=global_step < warmup_steps,
                           true_fn=lambda: warmup_lr,
                           false_fn=lambda: lr)
        return lr

    def poly_rate_fn(global_step):
        """Handles linear scaling rule, gradual warmup, and LR decay.
        The learning rate starts at 0, then it increases linearly per step.  After
        FLAGS.poly_warmup_epochs, we reach the base learning rate (scaled to account
        for batch size). The learning rate is then decayed using a polynomial rate
        decay schedule with power 2.0.
        Args:
          global_step: the current global_step
        Returns:
          returns the current learning rate
        """

        # Learning rate schedule for LARS polynomial schedule
        if flags.FLAGS.batch_size < 8192:
            plr = 5.0
            w_epochs = 5
        elif flags.FLAGS.batch_size < 16384:
            plr = 10.0
            w_epochs = 5
        elif flags.FLAGS.batch_size < 32768:
            plr = 25.0
            w_epochs = 5
        else:
            plr = 32.0
            w_epochs = 14

        w_steps = int(w_epochs * batches_per_epoch)
        wrate = (plr * tf.cast(global_step, tf.float32) / tf.cast(
            w_steps, tf.float32))

        # TODO(pkanwar): use a flag to help calc num_epochs.
        num_epochs = 90
        train_steps = batches_per_epoch * num_epochs

        min_step = tf.constant(1, dtype=tf.int64)
        decay_steps = tf.maximum(min_step, tf.subtract(global_step, w_steps))
        poly_rate = tf.train.polynomial_decay(
            plr,
            decay_steps,
            train_steps - w_steps + 1,
            power=2.0)
        return tf.where(global_step <= w_steps, wrate, poly_rate)

    # For LARS we have a new learning rate schedule
    if flags.FLAGS.enable_lars:
        return poly_rate_fn

    return learning_rate_fn



def cifar10_model_fn(features, labels, mode, params):
    """Model function for CIFAR-10"""
    features = tf.reshape(features, [-1, HEIGHT, WIDTH, NUM_CHANNELS])

    learning_rate_fn = learning_rate_with_decay(batch_size=params['batch_size'],
                                                batch_denom=32,
                                                num_images=NUM_IMAGES['train'],
                                                boundary_epochs=[91, 126, 182], decay_rates=[1, 0.1, 0.01, 0.001])

    weight_decay = 2e-4

    def loss_filter_fn(_):
        return True

    return resnet_model_fn(features=features,
                           labels=labels,
                           mode=mode,
                           model_class=Cifar10Model,
                           resnet_size=params['resnet_size'],
                           weight_decay=weight_decay,
                           learning_rate_fn=learning_rate_fn,
                           momentum=0.9,
                           resnet_version=params['resnet_version'],
                           loss_scale=params['loss_scale'],
                           loss_filter_fn=loss_filter_fn,
                           dtype=params['dtype'],
                           fine_tune=params['fine_tune'])


def define_resnet_flags(resnet_size_choices=None, dynamic_loss_scale=False):
    """define the params Add flags and validators for ResNet.
    cifar_flags
    data_dir:the path of data
    model_dir:the path of model
    resnet_size: the size of resnet
    train_epochs: the epochs of train
    epochs_betweeen_evals:a flag to specify the frequency of testing.
    batch_size:
    image_bytes_as_serving_input:

    resnet_flags

    """
    flags.DEFINE_string(name="data_dir",
                        short_name="dd", default="/tmp",
                        help="the location of the input data")
    flags.DEFINE_string(name="model_dir",
                        short_name='md', default="/tmp",
                        help="teh location of the model checkpoint files.")
    flags.DEFINE_enum(name="mode", default="train",enum_values=["train",'evaluate',"test"],
                      help="the mode of function,must be train or test")

    flags.DEFINE_bool(name="clean",
                      default=False,
                      help="if set, model dir will be remove if it exists.")
    flags.DEFINE_integer(name="train_epochs",
                         short_name="te",
                         default="20",
                         help="the number of epochs used to trian.")
    flags.DEFINE_float(name="stop_threshold",
                       short_name="st",
                       default=None,
                       help="If passed, training will stop at the earlier of "
                            "train_epochs and when the evaluation metric is  "
                            "greater than or equal to stop_threshold.")
    flags.DEFINE_string(name="export_dir",
                        short_name="ed", default=None,
                        help="if set, a SavedModel serialization of the model will"
                             "be exported to this directory at the end of training")
    flags.DEFINE_integer(name="batch_size", short_name="bs", default=16,
                         help="Batch size for training and evaluation.")

    flags.DEFINE_enum(name="resnet_version", short_name="rv",
                      default="1", enum_values=["1", "2"],
                      help="Version of Resnet,1 or 2")
    flags.DEFINE_bool(name="fine_tune", short_name="ft",
                      default=False, help="if not None initialize all"
                                         "the network except the final layer with these values.")

    flags.DEFINE_string(name="pretrained_model_checkpoint_path",
                        short_name="pmcp", default=None,
                        help="If not None initialize all the network except the final layer with "
                             "these values")
    flags.DEFINE_bool(
        name='enable_lars', default=False,
        help='Enable LARS optimizer for large batch training.')

    flags.DEFINE_float(
        name='label_smoothing', default=0.0,
        help='Label smoothing parameter used in the softmax_cross_entropy')
    flags.DEFINE_float(
        name='weight_decay', default=1e-4,
        help='Weight decay coefficiant for l2 regularization.')



    choice_kwargs = dict(
        name='resnet_size', short_name='rs', default='50',
        help='The size of the ResNet model to use.')

    if resnet_size_choices is None:
        flags.DEFINE_string(**choice_kwargs)
    else:
        flags.DEFINE_enum(enum_values=resnet_size_choices, **choice_kwargs)


    def set_default(**kwargs):
        for key, value in kwargs.items():
            flags.FLAGS.set_default(name=key, value=value)

    set_default(data_dir='..\\dataset\\cifar-10\\',
                model_dir='..\\model\\cifar10_model',
                mode="train",
                resnet_size='56',
                train_epochs=182,
                batch_size=16)


def run_cifar(flag_obj):
    """Run ResNet CIFAR-10 training and eval loop
    Args:
        flag_obj: An object containing parsed flag values.

    Returns:
        Dictionary of results,Including final accuracy.
    """
    if flag_obj.mode == "train":
        tf.compat.v1.logging.info("starting training")

        resnet_main(flag_obj, cifar10_model_fn, input_fn, DATASET_NAME,
                    shape=[HEIGHT, WIDTH, NUM_CHANNELS])




    else:
        tf.compat.v1.logging.info("testing")

    return None


def main(argv=()):
    del argv
    run_cifar(flags.FLAGS)


if __name__ == "__main__":
    define_resnet_flags()
    absl_app.run(main)
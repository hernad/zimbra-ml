"""
created: 9/8/2017
(c) copyright 2017 Synacor, Inc

This is a neural network that can take both a small number of words from the subject and body, and
a few features of the e-mail, generated by relationships of the contacts and domains in the address block
to the user account as analytics, as well as any other features that may be useful.
"""
from neon.models.model import Model
from neon.layers import MergeMultistream, LSTM, Affine, RecurrentSum, Tree, BranchNode, SkipNode, Conv, Dropout
from neon.layers import MergeBroadcast, LookupTable, Reshape
from neon.initializers import GlorotUniform, Kaiming, Uniform
from neon.optimizers import Adam
from neon.transforms import Softmax, Logistic, Rectlin, Explin
from zmlcore.licensed.layers import NoisyDropout, OutputDeltaBuffer


class ClassifierNetwork(Model):
    def __init__(self, overlapping_classes=None, exclusive_classes=None, analytics_input=True,
                 network_type='conv_net', num_words=60, width=100, lookup_size=0, lookup_dim=0, optimizer=Adam()):
        assert (overlapping_classes is not None) or (exclusive_classes is not None)

        self.width = width
        self.num_words = num_words
        self.overlapping_classes = overlapping_classes
        self.exclusive_classes = exclusive_classes
        self.analytics_input = analytics_input
        self.recurrent = network_type == 'lstm'
        self.lookup_size = lookup_size
        self.lookup_dim = lookup_dim

        init = GlorotUniform()
        activation = Rectlin(slope=1E-05)
        gate = Logistic()

        input_layers = self.input_layers(analytics_input, init, activation, gate)

        if self.overlapping_classes is None:
            output_layers = [Affine(len(self.exclusive_classes), init, activation=Softmax())]
        elif self.exclusive_classes is None:
            output_layers = [Affine(len(self.overlapping_classes), init, activation=Logistic())]
        else:
            output_branch = BranchNode(name='exclusive_overlapping')
            output_layers = Tree([[SkipNode(),
                                   output_branch,
                                   Affine(len(self.exclusive_classes), init, activation=Softmax())],
                                  [output_branch,
                                   Affine(len(self.overlapping_classes), init, activation=Logistic())]])
        layers = [input_layers,
                  # this is where inputs meet, and where we may want to add depth or
                  # additional functionality
                  Dropout(keep=0.8),
                  output_layers]
        super(ClassifierNetwork, self).__init__(layers, optimizer=optimizer)

    def _epoch_fit(self, dataset, callbacks):
        """
        Just insert ourselves to shuffle the dataset each epoch
        :param dataset:
        :param callbacks:
        :return:
        """
        if hasattr(dataset, 'shuffle'):
            dataset.shuffle()

        return super(ClassifierNetwork, self)._epoch_fit(dataset, callbacks)

    def input_layers(self, analytics_input, init, activation, gate):
        """
        return the input layers. we currently support convolutional and LSTM
        :return:
        """
        if self.recurrent:
            if analytics_input:
                # support analytics + content
                input_layers = MergeMultistream([
                    [LSTM(300, init, init_inner=Kaiming(), activation=activation, gate_activation=gate,
                          reset_cells=True),
                     RecurrentSum()],
                    [Affine(30, init, activation=activation)]],
                    'stack')
            else:
                # content only
                input_layers = [LSTM(300, init, init_inner=Kaiming(), activation=activation, gate_activation=gate,
                                     reset_cells=True),
                                RecurrentSum()]
        else:
            if analytics_input:
                # support analytics + content
                input_layers = MergeMultistream([self.conv_net(activation),
                                                 [Affine(30, init, activation=Logistic())]],
                                                'stack')
            else:
                # content only
                input_layers = self.conv_net(activation)

        return input_layers

    def conv_net(self, activation, init=Kaiming(), version=-1):
        width = max([self.width, self.lookup_dim])
        if version == -1:
            if self.lookup_size:
                pre_layers = [
                    LookupTable(vocab_size=self.lookup_size, embedding_dim=width, init=GlorotUniform()),
                    Reshape((1, self.num_words, width)),
                ]
                first_width = width
            else:
                pre_layers = [
                    Conv((1, width, width), padding=0, init=init, activation=activation)
                ]
                first_width = 1

            return pre_layers + \
                   [
                       MergeBroadcast(
                           [
                               [
                                   Conv((3, first_width, 15), padding={'pad_h': 1, 'pad_w': 0}, init=init,
                                        activation=activation)
                               ],
                               [
                                   Conv((5, first_width, 15), padding={'pad_h': 2, 'pad_w': 0}, init=init,
                                        activation=activation)
                               ],
                               [
                                   Conv((7, first_width, 15), padding={'pad_h': 3, 'pad_w': 0}, init=init,
                                        activation=activation)
                               ],
                           ],
                           merge='depth'
                       ),
                       NoisyDropout(keep=0.5, noise_pct=1.0, noise_std=0.001),
                       Conv((5, 1, 15), strides={'str_h': 2 if self.num_words > 59 else 1,
                                                 'str_w': 1}, padding=0, init=init,
                            activation=activation),
                       NoisyDropout(keep=0.9, noise_pct=1.0, noise_std=0.00001),
                       Conv((3, 1, 9), strides={'str_h': 2, 'str_w': 1}, padding=0, init=init,
                            activation=activation),
                       NoisyDropout(keep=0.9, noise_pct=1.0, noise_std=0.00001),
                       Conv((9, 1, 9), strides={'str_h': 2, 'str_w': 1}, padding=0, init=init,
                            activation=activation)
                   ]

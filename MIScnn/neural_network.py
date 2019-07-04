#-----------------------------------------------------#
#                   Library imports                   #
#-----------------------------------------------------#
#External libraries
from keras.models import model_from_json
from keras.optimizers import Adam
import numpy
import math
#Internal libraries/scripts
from data_io import case_loader, save_prediction, batch_npz_cleanup
from preprocessing import preprocessing_MRIs
from data_generator import DataGenerator
from utils.matrix_operations import concat_3Dmatrices
from utils.callback import TrainingCallback
from models.unet_muellerdo import Unet
from models.metrics import dice_coefficient, dice_classwise, tversky_loss

#-----------------------------------------------------#
#                Neural Network - Class               #
#-----------------------------------------------------#
class NeuralNetwork:
    # Initialize class variables
    model = None
    config = None
    metrics = [dice_coefficient, dice_classwise,
              'categorical_accuracy', 'categorical_crossentropy']


    # Create a Convolutional Neural Network with Keras
    def __init__(self, config):
        model = Unet(input_shape=config["input_shape"],
                     n_labels=config["classes"],
                     activation="softmax")
        model.compile(optimizer=Adam(lr=config["learninig_rate"]),
                      loss=tversky_loss,
                      metrics=self.metrics)
        self.model = model
        self.config = config

    # Train the Neural Network model on the provided case ids
    def train(self, cases):
        # Preprocess Magnetc Resonance Images
        batchPointer = preprocessing_MRIs(cases, self.config,
                                          training=True,
                                          validation=False)
        # Initialize Data Generator
        dataGen = DataGenerator(batchPointer,
                                model_path=self.config["model_path"],
                                training=True,
                                shuffle=self.config["shuffle"])
        # Run training process with the Keras fit_generator
        self.model.fit_generator(generator=dataGen,
                                 epochs=self.config["epochs"],
                                 max_queue_size=self.config["max_queue_size"])
        # Clean up temporary npz files required for training
        batch_npz_cleanup()

    # Predict with the Neural Network model on the provided case ids
    def predict(self, cases):
        # Iterate over each case
        for id in cases:
            # Preprocess Magnetc Resonance Images
            batchPointer = preprocessing_MRIs([id], self.config, training=False)
            # Initialize Data generator
            dataGen = DataGenerator(batchPointer,
                                    model_path=self.config["model_path"],
                                    training=False,
                                    shuffle=False)
            # Run prediction process with the Keras predict_generator
            pred_seg = self.model.predict_generator(
                                generator=dataGen,
                                max_queue_size=self.config["max_queue_size"])
            # Reload MRI object from disk to cache
            mri = case_loader(id, self.config["data_path"],
                              load_seg=False)
            # Concatenate patches into a single 3D matrix back
            pred_seg = concat_3Dmatrices(patches=pred_seg,
                                         image_size=mri.vol_data.shape,
                                         window=self.config["patch_size"],
                                         overlap=self.config["overlap"])
            # Transform probabilities to classes
            pred_seg = numpy.argmax(pred_seg, axis=-1)
            # Backup segmentation prediction in output directory
            save_prediction(pred_seg, id, self.config["output_path"])
        # Clean up temporary npz files required for training
        batch_npz_cleanup()

    # Evaluate the Neural Network model on the provided case ids
    def evaluate(self, casesTraining, casesValidation):
        # Preprocess Magnetc Resonance Images for the Training data
        batchPointer_training = preprocessing_MRIs(casesTraining,
                                         self.config,
                                         training=True,
                                         validation=False)
        # Preprocess Magnetc Resonance Images for the Validation data
        batchPointer_validation = preprocessing_MRIs(casesValidation,
                                         self.config,
                                         training=True,
                                         validation=True)
        # Initialize Training Data Generator
        dataGen_train = DataGenerator(batchPointer_training,
                                      model_path=self.config["model_path"],
                                      training=True,
                                      shuffle=self.config["shuffle"])
        # Initialize Validation Data Generator
        dataGen_val = DataGenerator(batchPointer_validation,
                                    model_path=self.config["model_path"],
                                    training=True,
                                    shuffle=self.config["shuffle"])
        # Initialize custom Keras Callback to backup evaluation scores
        fitting_callback = TrainingCallback(self.config["evaluation_path"])
        # Run training & validation process with the Keras fit_generator
        history = self.model.fit_generator(generator=dataGen_train,
                                 validation_data=dataGen_val,
                                 callbacks=[fitting_callback],
                                 epochs=self.config["epochs"],
                                 max_queue_size=self.config["max_queue_size"])
        # Clean up temporary npz files required for training
        batch_npz_cleanup()
        # Return the training & validation history
        return history

    # Dump model to file
    def dump(self, path):
        # Serialize model to JSON
        model_json = self.model.to_json()
        with open("model/model.json", "w") as json_file:
            json_file.write(model_json)
        # Serialize weights to HDF5
        self.model.save_weights("model/weights.h5")

    # Load model from file
    def load(self, path):
        # Load json and create model
        json_file = open('model/model.json', 'r')
        loaded_model_json = json_file.read()
        json_file.close()
        self.model = model_from_json(loaded_model_json)
        # Load weights into new model
        self.model.load_weights("model/weights.h5")
        # Compile model
        self.model.compile(optimizer=Adam(lr=self.config["learninig_rate"]),
                           loss=tversky_loss,
                           metrics=self.metrics)
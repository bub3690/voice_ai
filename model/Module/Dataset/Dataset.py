import pickle
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
import librosa

from .Data import PhraseData, FusionData, OpensmileData, GlottalData
import torchaudio.transforms as T
from torch.nn.utils.rnn import pad_sequence
from Utils.Utils import statistical_feature
from scipy.signal import find_peaks
from scipy.interpolate import interp1d

import opensmile

def load_pickle_data(path):
    with open(path, 'rb') as f:
        data = pickle.load(f)
    return data




###
# augmentation
class Cutout(object):
    """Randomly mask out one or more patches from an image.
    Args:
        n_holes (int): Number of patches to cut out of each image.
        length (int): The length (in pixels) of each square patch.
    """
    def __init__(self, n_holes, length):
        self.n_holes = n_holes
        self.length = length

    def __call__(self, img):
        """
        Args:
            img (Tensor): Tensor image of size (C, H, W).
        Returns:
            Tensor: Image with n_holes of dimension length x length cut out of it.
        """
        h = img.size(1)
        w = img.size(2)

        mask = np.ones((h, w), np.float32)

        for n in range(self.n_holes):
            y = np.random.randint(50,78)
            x = np.random.randint(w)

            y1 = np.clip(y - self.length // 2, 0, h)
            y2 = np.clip(y + self.length // 2, 0, h)
            x1 = np.clip(x - self.length // 2, 0, w)
            x2 = np.clip(x + self.length // 2, 0, w)

            mask[y1: y2, x1: x2] = 0.

        mask = torch.from_numpy(mask)
        mask = mask.expand_as(img)
        img = img * mask

        return img

###

# # 데이터 정의
# - 추가적으로 데이터의 크기를 맞춰주기 위해 3초로 padding 및 truncate 실시 https://sequencedata.tistory.com/25 FixAudioLength
# - 논문에서는 400frame으로 설정.(여기서는 500frame)
# - 전처리 방법 결정.
# 
# 데이터 로더

classes = ["healthy","pathology"]


class svd_dataset(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mfcc_params,
                mel_params,
                spectro_params,
                is_normalize,
                norm_mean_list,
                norm_std_list,
                augmentation=[],
                augment_params=dict(),
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        # sweep params
        self.mel_params = mel_params
        self.spectro_params = spectro_params
        self.mfcc_params = mfcc_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size

        self.is_train = is_train

        #noramlize 관련
        self.is_normalize = is_normalize
        if is_normalize:
            self.normalize=transforms.Normalize((norm_mean_list[1],norm_mean_list[1],norm_mean_list[1]),(norm_std_list[1],norm_std_list[1],norm_std_list[1]))
        else:
            self.normalize=None

        #augmentation들
        self.crop = None
        self.spec_augment = None
        self.augment_params = augment_params
        
        if "crop" in augmentation:
            self.crop = transforms.RandomApply([
                                                Cutout(self.augment_params['crop'][0],
                                                self.augment_params['crop'][1]),
                                                ],
                                                p = self.augment_params['crop'][2])
        if "spec_augment" in augmentation:
            self.spec_augment = transforms.RandomApply([
                                                    transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
                                                                        T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
                                               ],
                                               p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        1. path를 받아서, 소리에서 mfcc를 추출
        2. mfcc를 224프레임으로 패딩.
        3. resnet에 사용되기 위해 3채널로 복사(rgb 처럼)
        4. 0~1 정규화
        
        """
        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-phrase.wav'] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        if sig.shape[0] > self.mel_params["sr"]*2:
            origin_length = self.mel_params["sr"]*2
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        
        length = self.mel_params["sr"]*2 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)        
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###
        
        mel_feature = librosa.feature.melspectrogram(y=sig,
                                                    sr=self.mel_params["sr"],
                                                    # hyp param
                                                    n_mels = self.mel_params["n_mels"],
                                                    n_fft = self.mel_params["n_fft"],
                                                    win_length = self.mel_params["win_length"],
                                                    hop_length = self.mel_params["hop_length"],
                                                    fmax = self.mel_params["f_max"]
                                                    )
        mel_feature = librosa.core.power_to_db(mel_feature,ref=np.max) 
        
        
        if self.transform:
            mel_feature = self.transform(mel_feature).type(torch.float32)# 데이터 0~1 정규화
            MSF = torch.stack([mel_feature, mel_feature, mel_feature])# 3채널로 복사.
            MSF = MSF.squeeze(dim=1)    
            
            # global normalize
            if self.normalize:
                MSF = self.normalize(MSF)
            

            if self.is_train:
                #spec augment
                if self.crop:
                    MSF = self.crop(MSF)
                if self.spec_augment:
                    MSF = self.spec_augment(MSF)

        else:
            pass
            #print("else")
            mel_feature = torch.from_numpy(mel_feature).type(torch.float32)
            mel_feature=mel_feature.unsqueeze(0)#cnn 사용위해서 추가
            #MFCCs = MFCCs.permute(2, 0, 1)
        return MSF, self.classes.index(self.label[idx])

class svd_dataset_harmonic(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mfcc_params,
                mel_params,
                spectro_params,
                is_normalize,
                norm_mean_list,
                norm_std_list,
                is_train=False,
                transform=None,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform
        
        

        # sweep params
        self.mel_params = mel_params
        self.spectro_params = spectro_params
        self.mfcc_params = mfcc_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size

        #noramlize 관련
        self.is_normalize = is_normalize
        if is_normalize:
            self.normalize=transforms.Normalize((norm_mean_list[1],norm_mean_list[1],norm_mean_list[1]),(norm_std_list[1],norm_std_list[1],norm_std_list[1]))
        else:
            self.normalize=None

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        1. path를 받아서, 소리에서 mfcc를 추출
        2. mfcc를 224프레임으로 패딩.
        3. resnet에 사용되기 위해 3채널로 복사(rgb 처럼)
        4. 0~1 정규화
        
        """
        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-phrase.wav'] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        if sig.shape[0] > self.mel_params["sr"]*2:
            origin_length = self.mel_params["sr"]*2
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        
        length = self.mel_params["sr"]*2 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)        
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###
        
        mel_feature = librosa.feature.melspectrogram(y=sig,
                                                    sr=self.mel_params["sr"],
                                                    # hyp param
                                                    n_mels = self.mel_params["n_mels"],
                                                    n_fft = self.mel_params["n_fft"],
                                                    win_length = self.mel_params["win_length"],
                                                    hop_length = self.mel_params["hop_length"],
                                                    fmax = self.mel_params["f_max"]
                                                    )
        mel_feature = librosa.core.power_to_db(mel_feature,ref=np.max)

        mel_feature1 = mel_feature.copy()
        mel_feature2 = mel_feature.copy()
        mel_feature3 = mel_feature.copy()

        mel_feature1[:42,:] = 0
        mel_feature2[42:42*2,:] = 0
        mel_feature3[42*2:42*3,:] = 0

        if self.transform:
            mel_feature1 = self.transform(mel_feature1).type(torch.float32)# 
            mel_feature2 = self.transform(mel_feature2).type(torch.float32)# 
            mel_feature3 = self.transform(mel_feature3).type(torch.float32)# 

            MSF = torch.stack([mel_feature1, mel_feature2, mel_feature3])# 3채널로 복사.
            MSF = MSF.squeeze(dim=1)
            
            # global normalize
            if self.normalize:
                MSF = self.normalize(MSF)
        else:
            pass
            #print("else")
            mel_feature = torch.from_numpy(mel_feature).type(torch.float32)
            mel_feature=mel_feature.unsqueeze(0)#cnn 사용위해서 추가
            #MFCCs = MFCCs.permute(2, 0, 1)
        return MSF, self.classes.index(self.label[idx])



class svd_dataset_msf(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mfcc_params,
                mel_params,
                spectro_params,
                is_normalize,
                norm_mean_list,
                norm_std_list,
                augmentation=[],
                augment_params=dict(),
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform
        
        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        self.spectro_params = spectro_params
        self.mfcc_params = mfcc_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size

        #noramlize 관련
        self.is_normalize = is_normalize
        if is_normalize:
            self.normalize=transforms.Normalize((norm_mean_list[0],norm_mean_list[1],norm_mean_list[1]),(norm_std_list[0],norm_std_list[1],norm_std_list[1]))
            self.mfcc_normalize=(norm_mean_list[2],norm_std_list[2])
        else:
            self.normalize=None
            self.mfcc_normalize=None


        #augmentation들
        self.crop = None
        self.spec_augment = None
        self.augment_params = augment_params
        
        if "crop" in augmentation:
            self.crop = transforms.RandomApply([
                                                Cutout(self.augment_params['crop'][0],
                                                self.augment_params['crop'][1]),
                                                ],
                                                p = self.augment_params['crop'][2])
        if "spec_augment" in augmentation:
            self.spec_augment = transforms.RandomApply([
                                                    transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
                                                                        T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
                                               ],
                                               p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        1. path를 받아서, 소리에서 mfcc를 추출
        2. mfcc를 224프레임으로 패딩.
        3. resnet에 사용되기 위해 3채널로 복사(rgb 처럼)
        4. 0~1 정규화
        
        """
        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-phrase.wav'] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        if sig.shape[0] > self.mfcc_params["sr"]*2:
            origin_length = self.mfcc_params["sr"]*2
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        
        length = self.mfcc_params["sr"]*2 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)        
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###
        
        stft = librosa.stft(sig, win_length=self.spectro_params["win_length"],
                                n_fft=self.spectro_params["n_fft"],
                                hop_length=self.spectro_params["hop_length"]
                            )
        magnitude = np.abs(stft)
        log_spectrogram = librosa.amplitude_to_db(magnitude)
        
        log_spectrogram = log_spectrogram[:self.mel_params["n_mels"],:] 
        
        mel_feature = librosa.feature.melspectrogram(y=sig,
                                                    sr=self.mel_params["sr"],
                                                    # hyp param
                                                    n_mels = self.mel_params["n_mels"],
                                                    n_fft = self.mel_params["n_fft"],
                                                    win_length = self.mel_params["win_length"],
                                                    hop_length = self.mel_params["hop_length"],
                                                    fmax = self.mel_params["f_max"]
                                                    )
        mel_feature = librosa.core.power_to_db(mel_feature,ref=np.max) 

        sig_torch=torch.tensor(sig, dtype=torch.float32)
        
        MFCC = T.MFCC(
                        sample_rate = self.mfcc_params["sr"],
                        n_mfcc = self.mfcc_params["n_mfcc"],
                        melkwargs={
                            'n_fft': self.mfcc_params["n_fft"],
                            'n_mels': self.mfcc_params["n_mels"],
                            'hop_length': self.mfcc_params["hop_length"],
                            'mel_scale': self.mfcc_params["mel_scale"],
                            'win_length' : self.mfcc_params["win_length"],
                            'f_max': self.mfcc_params["f_max"]
                        }
                    )
        
        MFCCs=MFCC(sig_torch)
        
        MFCCs = MFCCs[1:,]
        if self.mfcc_normalize:
           MFCCs=(MFCCs-self.mfcc_normalize[0])/self.mfcc_normalize[1]
        (nframes, ncoeff) = MFCCs.shape
        cep_lifter = self.mfcc_params["lifter"]
        
        time_len = mel_feature.shape[1]
 
        
        if cep_lifter > 0:
            n = np.arange(ncoeff)
            lift = 1 + (cep_lifter / 2) * np.sin(np.pi * n / cep_lifter)
            MFCCs *= lift

        
        
        if self.transform:
            log_spectrogram = self.transform(log_spectrogram).type(torch.float32)
            mel_feature = self.transform(mel_feature).type(torch.float32)# 데이터 0~1 정규화
            MSF = torch.stack([log_spectrogram, mel_feature, mel_feature])# 3채널로 복사.
            MSF = MSF.squeeze(dim=1)
            
            MFCCs=MFCCs.type(torch.float32)# 타입 변화
            #MFCCs = self.transform(MFCCs).type(torch.float32)# 데이터 0~1 정규화
            MFCCs=MFCCs.squeeze().mean(axis=1)
            
            #mfcc norm
            #if self.mfcc_normalize:
            #    MFCCs=(MFCCs-self.mfcc_normalize[0])#/self.mfcc_normalize[1]            
            
            # global normalize
            if self.normalize:
                #MFCCs=self.normalize(MFCCs)
                MSF = self.normalize(MSF)
            if self.is_train:
                #spec augment
                if self.crop:
                    MSF = self.crop(MSF)
                if self.spec_augment:
                    MSF = self.spec_augment(MSF)
    
        else:
            pass
            #print("else")
            mel_feature = torch.from_numpy(mel_feature).type(torch.float32)
            mel_feature=mel_feature.unsqueeze(0)#cnn 사용위해서 추가
            #MFCCs = MFCCs.permute(2, 0, 1)
        return MSF,MFCCs, self.classes.index(self.label[idx])        


class svd_dataset_wav(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-'+self.dataset+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        if sig.shape[0] > self.mel_params["sr"]*3:
            origin_length = self.mel_params["sr"]*3
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        #print(sig.shape)
        # sig = np.tile(sig,(2,))

        length = self.mel_params["sr"]*3 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        
        # if length-sig.shape[0] >0:
        #     sig=np.pad(sig,(0,length-sig.shape[0]),mode='wrap')#상하, 좌우
        # else:
        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###

        sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
        
        
        
        sig=sig.unsqueeze(0)
        
        return sig, self.classes.index(self.label[idx]), str(self.path_list[idx]), origin_length

class svd_dataset_wav_smile(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                norm_mean_list=None,
                norm_std_list=None,
                scaler_list=None,         
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset

        self.smile_dict=OpensmileData.opensmile_dict
        #noramlize 관련

        if norm_mean_list != None and len(norm_mean_list) >0:
            self.norm_mean_list = norm_mean_list
            self.norm_std_list = norm_std_list

        self.scaler_list = OpensmileData.scaler_list

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-'+self.dataset+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        if sig.shape[0] > self.mel_params["sr"]*3:
            origin_length = self.mel_params["sr"]*3
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        
        handcrafted = self.smile_dict[str(self.path_list[idx])+'-'+self.dataset+'.wav']
        #####

        #handcrafted normalize
        if len(self.scaler_list) != 0:
            handcrafted = self.scaler_list[0].transform(handcrafted.to_numpy())

        length = self.mel_params["sr"]*3 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###


        sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
        sig=sig.unsqueeze(0)
        
        #여기 뭐지.
        if self.scaler_list == None or len(self.scaler_list)==0:
            handcrafted = torch.from_numpy(handcrafted.to_numpy()).type(torch.float32).squeeze(0)
        else:
            handcrafted = torch.from_numpy(handcrafted).type(torch.float32).squeeze(0)
        return sig, handcrafted, self.classes.index(self.label[idx]), str(self.path_list[idx]), origin_length



class svd_dataset_wav_hindawi_handcrafted(Dataset):
    """
    paper : Comparative Analysis of CNN and RNN for Voice Pathology Detection
    wav만 취득하기.
    
    """
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련
          
        

    # Extract Rolloff
    def extract_rolloff(audio_file,sr):
        rolloff = librosa.feature.spectral_rolloff(y=audio_file, sr=sr).squeeze(axis=0)
        return rolloff

    # Extract ZCR (Zero-Crossing Rate)
    def extract_zcr(audio_file,sr):
        zcr = librosa.feature.zero_crossing_rate(audio_file).squeeze(axis=0)
        return zcr


    def extract_energy_entropy(audio_file,sr):
        # Load the audio signal
        # 음성 신호에서 에너지를 계산합니다.
        energy = np.sum(audio_file ** 2)

        # 에너지 분포의 불확실성의 척도로 에너지 엔트로피를 계산합니다.
        entropy = -np.sum(energy * np.log2(energy))

        return entropy

    # 6. Extract Spectral Flux
    def extract_spectral_flux(audio_file,sr):
        spectral_flux = librosa.onset.onset_strength(y=audio_file, sr=sr)
        return spectral_flux

    # 7. Extract Spectral Centroid
    def extract_spectral_centroid(audio_file,sr):
        spectral_centroid = librosa.feature.spectral_centroid(y=audio_file, sr=sr).squeeze(axis=0)
        return spectral_centroid

    # 8. Extract Energy
    def extract_energy(audio_file,sr):
        energy = librosa.feature.rms(y=audio_file).squeeze(axis=0)
        return energy

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.
        # 
        # 
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-'+self.dataset+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        if sig.shape[0] > self.mel_params["sr"]*3:
            origin_length = self.mel_params["sr"]*3
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        #print(sig.shape)
        # sig = np.tile(sig,(2,))

        length = self.mel_params["sr"]*3 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        
        
        #spectral_envelope = svd_dataset_wav_handcrafted.get_spectral_envelope(sig,self.mel_params["sr"]) #40개
        f0 = librosa.yin(sig, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), frame_length=1024, hop_length=512)
        f0 = statistical_feature(f0)
        rolloff = svd_dataset_wav_hindawi_handcrafted.extract_rolloff(sig,self.mel_params["sr"])
        rolloff = statistical_feature(rolloff)
        zcr = svd_dataset_wav_hindawi_handcrafted.extract_zcr(sig,self.mel_params["sr"])
        zcr = statistical_feature(zcr)
        energy_entropy = svd_dataset_wav_hindawi_handcrafted.extract_energy_entropy(sig,self.mel_params["sr"])
        spectral_flux = svd_dataset_wav_hindawi_handcrafted.extract_spectral_flux(sig,self.mel_params["sr"])
        spectral_flux = statistical_feature(spectral_flux)
        spectral_centroid = svd_dataset_wav_hindawi_handcrafted.extract_spectral_centroid(sig,self.mel_params["sr"])
        spectral_centroid = statistical_feature(spectral_centroid)
        energy = svd_dataset_wav_hindawi_handcrafted.extract_energy(sig,self.mel_params["sr"])
        energy = statistical_feature(energy)
        # print('rolloff',rolloff)
        # print('zcr',zcr)
        # print('energy_entropy',energy_entropy)
        # print('spectral_flux',spectral_flux)
        # print('spectral_centroid',spectral_centroid)
        # print('energy',energy)
        
        

        handcrafted = np.hstack((f0,rolloff,zcr,energy_entropy,spectral_flux,spectral_centroid,energy))
        # mfcc도 추가해서 넣기.

        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###

        sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
        sig=sig.unsqueeze(0)
        #import pdb;pdb.set_trace()
        handcrafted = torch.from_numpy(handcrafted).type(torch.float32)# 타입 변화
        # mfcc 는 후에 추가.
        
        return sig,handcrafted, self.classes.index(self.label[idx]), str(self.path_list[idx]), origin_length




class svd_dataset_wav_handcrafted(Dataset):
    """
    paper : Multi-modal voice pathology detection architecture based on deep and handcrafted feature fusion.
    wav만 취득하기.
    
    """
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련
        
        self.mfcc_scale = T.MFCC(
            sample_rate=16000,
            n_mfcc=30,
            melkwargs={
                "n_fft":self.mel_params["n_fft"],
                "win_length":self.mel_params["win_length"],
                "hop_length":self.mel_params["hop_length"],
                "n_mels":self.mel_params["n_mels"],
                "f_min":130,
                "f_max":6800,
                "center":True,
                "pad_mode":"constant",
                "power":2.0,
                "norm":"slaney",
                "mel_scale":"slaney",
                "window_fn":torch.hann_window
            }
        )        
        


    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.
        # 
        # 
    def get_spectral_envelope(wav,sr):
        n_fft = 2048

        spec = librosa.stft(wav, n_fft=n_fft, hop_length=n_fft//4)
        spec_db = librosa.amplitude_to_db(abs(spec), ref=np.max)
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

        peaks, _ = find_peaks(spec_db, height=-30)
        envelope = interp1d(freqs[peaks], spec_db[peaks], kind='cubic', bounds_error=False, fill_value=-100)

        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))
        wav_env=pad1d(envelope(freqs[peaks]),40)
        return wav_env
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-'+self.dataset+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        if sig.shape[0] > self.mel_params["sr"]*3:
            origin_length = self.mel_params["sr"]*3
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        #print(sig.shape)
        # sig = np.tile(sig,(2,))

        length = self.mel_params["sr"]*3 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        
        
        #spectral_envelope = svd_dataset_wav_handcrafted.get_spectral_envelope(sig,self.mel_params["sr"]) #40개
        lpc = librosa.lpc(sig, order=30) # 30개
        f0 = librosa.yin(sig, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), frame_length=1024, hop_length=512)
        f0 = statistical_feature(f0)
        #spectral envelope 오류나니까 빼고 실험 완성하기.
        

        handcrafted = np.hstack((lpc,f0))
        # mfcc도 추가해서 넣기.

        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig = pad1d(sig,length)
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###

        sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
        sig=sig.unsqueeze(0)
        #import pdb;pdb.set_trace()
        mfcc = self.mfcc_scale(sig).squeeze(0).flatten()
        handcrafted = torch.from_numpy(handcrafted).type(torch.float32)# 타입 변화
        handcrafted = torch.concat((handcrafted,mfcc),dim=0)
        # mfcc 는 후에 추가.
        
        return sig,handcrafted, self.classes.index(self.label[idx]), str(self.path_list[idx]), origin_length




class svd_dataset_wav_three_segments(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        sig_tensor_fusion = []

        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-'+self.dataset+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]

        one_segment_legnth = origin_length//3
        
        sig1 = sig[:one_segment_legnth]
        sig2 = sig[one_segment_legnth:one_segment_legnth*2]
        sig3 = sig[one_segment_legnth*2:]

        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        #print(sig.shape)
        # sig = np.tile(sig,(2,))

        length = self.mel_params["sr"] #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        
        # if length-sig.shape[0] >0:
        #     sig=np.pad(sig,(0,length-sig.shape[0]),mode='wrap')#상하, 좌우
        # else:
        pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        sig1 = pad1d(sig1,length)
        sig2 = pad1d(sig2,length)
        sig3 = pad1d(sig3,length)

        
        ###signal norm
        sig1 = (sig1-sig1.mean())/sig1.std()
        sig2 = (sig2-sig2.mean())/sig2.std()
        sig3 = (sig3-sig3.mean())/sig3.std()
        ###

        sig1=torch.from_numpy(sig1).type(torch.float32)# 타입 변화
        sig2=torch.from_numpy(sig2).type(torch.float32)# 타입 변화
        sig3=torch.from_numpy(sig3).type(torch.float32)# 타입 변화
        
        
        
        sig1=sig1.unsqueeze(0)
        sig2=sig2.unsqueeze(0)
        sig3=sig3.unsqueeze(0)
        sig_tensor_fusion = [sig1,sig2,sig3]
        sig_tensor_fusion = torch.stack(sig_tensor_fusion)
        
        return sig_tensor_fusion, self.classes.index(self.label[idx]), str(self.path_list[idx]), origin_length



class svd_dataset_wav_eggfusion(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV,EGG 파일을 읽어서, MODEL에 전달.
        """
        sig_tensor = []
        for wav_dict in FusionData.dict_list:
            sample=list(wav_dict.keys())[0]
            if len(sample.split('-'))<=2:
                #phrase
                dataset_name=sample.split("-")[-1].split('.wav')[0]# phrase, egg
                sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
            else:
                #egg
                dataset_name=sample.split("-")[1]# phrase
                format_name=sample.split("-")[-1]# egg.wav

                sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'-'+format_name ]                 
            #sig = preemphasis(sig)
            
            origin_length = sig.shape[0]
            
            if sig.shape[0] > self.mel_params["sr"]*3:
                origin_length = self.mel_params["sr"]*3
            
            origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
            
            length = self.mel_params["sr"]*3 #sample rate *3 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
            pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
            sig = pad1d(sig,length)
            
            ###signal norm
            sig = (sig-sig.mean())/sig.std()
            ###

            sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
            sig=sig.unsqueeze(0)

            sig_tensor.append(sig)
        sig_tensor = torch.stack(sig_tensor)

        return sig_tensor, self.classes.index(self.label[idx]), str(self.path_list[idx]),origin_length   


class svd_dataset_wav_eggfusion_smile(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        self.smile_dict=OpensmileData.opensmile_dict
        #noramlize 관련
        self.scaler_list = OpensmileData.scaler_list
        
        
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV,EGG 파일을 읽어서, MODEL에 전달.
        """
        sig_tensor = []
        for wav_dict in FusionData.dict_list:
            sample=list(wav_dict.keys())[0]
            if len(sample.split('-'))<=2:
                #phrase
                dataset_name=sample.split("-")[-1].split('.wav')[0]# phrase, egg
                sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ]
                
                handcrafted = self.smile_dict[str(self.path_list[idx])+'-'+dataset_name+'.wav']
                #####

                #handcrafted normalize
                if len(self.scaler_list) != 0:
                    handcrafted = self.scaler_list[0].transform(handcrafted.to_numpy())                
            else:
                #egg
                dataset_name=sample.split("-")[1]# phrase
                format_name=sample.split("-")[-1]# egg.wav

                sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'-'+format_name ]                 
            #sig = preemphasis(sig)
            
            origin_length = sig.shape[0]
            
            if sig.shape[0] > self.mel_params["sr"]*3:
                origin_length = self.mel_params["sr"]*3
            
            origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
            
            length = self.mel_params["sr"]*3 #sample rate *3 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
            pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
            sig = pad1d(sig,length)
            
            ###signal norm
            sig = (sig-sig.mean())/sig.std()
            ###

            sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
            sig=sig.unsqueeze(0)

            sig_tensor.append(sig)
        sig_tensor = torch.stack(sig_tensor)
        if self.scaler_list == None or len(self.scaler_list)==0:
            handcrafted = torch.from_numpy(handcrafted.to_numpy()).type(torch.float32).squeeze(0)
        else:
            handcrafted = torch.from_numpy(handcrafted).type(torch.float32).squeeze(0)        

        return sig_tensor,handcrafted, self.classes.index(self.label[idx]), str(self.path_list[idx]), origin_length  





class svd_dataset_wav_eggfusion_handcrafted(Dataset):
    """
    paper : Multi-modal voice pathology detection architecture based on deep and handcrafted feature fusion 
    
    egg,wav와 handcrafted feature를 fusion하여 사용하는 데이터셋
    handcrafted feature : lpc,mfcc, F0,spectral slope

    """
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련
        
        self.mfcc_scale = T.MFCC(
            sample_rate=16000,
            n_mfcc=30,
            melkwargs={
                "n_fft":self.mel_params["n_fft"],
                "win_length":self.mel_params["win_length"],
                "hop_length":self.mel_params["hop_length"],
                "n_mels":self.mel_params["n_mels"],
                "f_min":130,
                "f_max":6800,
                "center":True,
                "pad_mode":"constant",
                "power":2.0,
                "norm":"slaney",
                "mel_scale":"slaney",
                "window_fn":torch.hann_window
            }
        )               

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV,EGG 파일을 읽어서, MODEL에 전달.
        """
        sig_tensor = []
        handcrafted_tensor = []
        for wav_dict in FusionData.dict_list:
            sample=list(wav_dict.keys())[0]
            if len(sample.split('-'))<=2:
                #phrase
                dataset_name=sample.split("-")[-1].split('.wav')[0]# phrase, egg
                sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
            else:
                #egg
                dataset_name=sample.split("-")[1]# phrase
                format_name=sample.split("-")[-1]# egg.wav

                sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'-'+format_name ]                 
            #sig = preemphasis(sig)
            
            origin_length = sig.shape[0]
            
            if sig.shape[0] > self.mel_params["sr"]*3:
                origin_length = self.mel_params["sr"]*3
            
            origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
            
            lpc = librosa.lpc(sig, order=30) # 30개
            f0 = librosa.yin(sig, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), frame_length=1024, hop_length=512)
            f0 = statistical_feature(f0)      
            handcrafted = np.hstack((lpc,f0))
            
            length = self.mel_params["sr"]*3 #sample rate *3 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
            pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
            sig = pad1d(sig,length)
            
            ###signal norm
            sig = (sig-sig.mean())/sig.std()
            ###

            sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
            sig=sig.unsqueeze(0)
            
            mfcc = self.mfcc_scale(sig).squeeze(0).flatten()
            handcrafted = torch.from_numpy(handcrafted).type(torch.float32)# 타입 변화
            handcrafted = torch.concat((handcrafted,mfcc),dim=0)            
            
            handcrafted_tensor.append(handcrafted)
            sig_tensor.append(sig)
        sig_tensor = torch.stack(sig_tensor)
        handcrafted_tensor = torch.cat(handcrafted_tensor)

        return sig_tensor,handcrafted_tensor, self.classes.index(self.label[idx]), str(self.path_list[idx]),origin_length   






class svd_dataset_wav_nopad(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        sig = PhraseData.phrase_dict[ str(self.path_list[idx])+'-'+self.dataset+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        # if sig.shape[0] > self.mel_params["sr"]*3:
        #     origin_length = self.mel_params["sr"]*3
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        #print(sig.shape)
        #sig = np.tile(sig,(2,))

        # length = self.mel_params["sr"]*3 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        # pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
        # sig = pad1d(sig,length)
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###

        sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
        #sig=sig.unsqueeze(0)
        
        return sig, self.classes.index(self.label[idx]), str(self.path_list[idx]), origin_length

def splice_data_same(x,y,path_list,origin_length,alpha=1.0):
    """같은 라벨에 대해서 splice 하는 경우. 아직 미구현"""
    '''return concated data. label pairs, lambda'''

    batch_size = x.size()[0]
    index = torch.randperm(batch_size).cuda()

    if alpha > 0:
        beta = torch.distributions.Beta(torch.tensor([alpha]), torch.tensor([alpha]))
        lam  = beta.sample( (batch_size,) ).squeeze()
        #print(lam)
    else:
        lam = 1
    #print(origin_length)
    first_len = torch.ceil(lam * origin_length).type(torch.LongTensor)
    second_len = torch.ceil( (1-lam) * origin_length[index]).type(torch.LongTensor)
    
    print(x[:,:,:first_len])
    mixed_x = torch.concat([x[:,:,:first_len],x[index,:,:second_len]],dim=2)
    y_a, y_b = y, y[index]
    return mixed_x,y_a, y_b,path_list




def splice_data(x,y,origin_length,alpha=1.0):
    '''return concated data. label pairs, lambda'''

    batch_size = len(x)
    index = torch.randperm(batch_size)

    if alpha > 0:
        beta = torch.distributions.Beta(torch.tensor([alpha]), torch.tensor([alpha]))
        lam  = beta.sample( (batch_size,) ).squeeze()
        #print(lam)
    else:
        lam = 1
    #print(origin_length)
    
    for batch_ind,second_ind in enumerate(index):
        first_len = torch.ceil(lam[batch_ind] * origin_length[batch_ind] ).int()
        second_len = torch.ceil( (1-lam[batch_ind]) * origin_length[second_ind]).int()
        x[batch_ind] = torch.concat([ x[batch_ind][:first_len], x[second_ind][:second_len] ],dim=0)

    #print(x)
    #x = pad_sequence(x).unsqueeze(1)
    y = torch.tensor(y,dtype=torch.int64)
    y_a, y_b = y, y[index]
    return x, y_a, y_b, lam



def mixup_data(x, y, alpha=1.0  ):
    '''Returns mixed inputs, pairs of targets, and lambda'''
    
    batch_size = x.size()[0]
    if alpha > 0:
        lam = np.random.beta(alpha, alpha)
    else:
        lam = 1    
    # if alpha > 0:
    #     beta = torch.distributions.Beta(torch.tensor(alpha), torch.tensor(alpha))
    #     lam = beta.sample((batch_size,) ).squeeze()
    # else:
    #     lam = 1

    
    index = torch.randperm(batch_size).cuda()
    mixed_x = lam * x + (1 - lam) * x[index, :]
    y = torch.tensor(y,dtype=torch.int64)
    y_a, y_b = y, y[index]
    return mixed_x, y_a, y_b, lam

def collate_mixup(batch):
    signal_list, label_list, path_list, length_list = [],[],[],[]
    
    for signal, label, path, length in batch:
        signal_list.append(signal)
        label_list.append(label)
        path_list.append(path)
        length_list.append(length)
    # pad 먼저 해야하는데, 어떻게 할지.
    signal_list=pad_sequence(signal_list,batch_first=True)
    signal_list, y_a, y_b,lam = mixup_data(signal_list,label_list)
    
    return signal_list,y_a,y_b,lam,path_list



def collate_splicing(batch):
    signal_list, label_list, path_list, length_list = [],[],[],[]
    
    for signal, label, path, length in batch:
        signal_list.append(signal)
        label_list.append(label)
        path_list.append(path)
        length_list.append(length)
    
    signal_list, y_a, y_b,lam = splice_data(signal_list,label_list,length_list)
    signal_list=pad_sequence(signal_list,batch_first=True)
    return signal_list,y_a,y_b,lam,path_list


class svd_dataset_wav_fusion(Dataset):
    """
    vowel late fusion. data file이 3개 인 경우.
    """
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        sig_tensor = []
        for wav_dict in FusionData.dict_list:
            dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
            sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
            #sig = preemphasis(sig)
            
            origin_length = sig.shape[0]
            
            if sig.shape[0] > self.mel_params["sr"]*2:
                origin_length = self.mel_params["sr"]*2
            
            origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
            
            length = self.mel_params["sr"]*2 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
            pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
            sig = pad1d(sig,length)
            
            ###signal norm
            sig = (sig-sig.mean())/sig.std()
            ###

            sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
            sig=sig.unsqueeze(0)

            sig_tensor.append(sig)
        sig_tensor = torch.stack(sig_tensor)

        return sig_tensor, self.classes.index(self.label[idx]), str(self.path_list[idx])


class svd_dataset_wav_concat(Dataset):
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='a_fusion',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        sig_tensor = []
        for wav_dict in FusionData.dict_list:
            dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
            sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
            #sig = preemphasis(sig)
            
            origin_length = sig.shape[0]
            
            #if sig.shape[0] > self.mel_params["sr"]*2:
            #    origin_length = self.mel_params["sr"]*2
            
            origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
            
            ###signal norm
            sig = (sig-sig.mean())/sig.std()
            ###

            sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
            sig=sig.unsqueeze(0)

            sig_tensor.append(sig)
            #print(sig.size())
        sig_tensor = torch.concat(sig_tensor,dim=1)
        #print(sig_tensor.size())
        
        length = 16000*4 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[:,0:i] if a.shape[1] > i else torch.hstack((a, torch.zeros((1,i-a.shape[1]))))        
        sig_tensor = pad1d(sig_tensor,length)


        return sig_tensor, self.classes.index(self.label[idx]), str(self.path_list[idx])

class svd_dataset_wav_phrase_vowel_concat(Dataset):
    """
    phrase + 3pitch vowel
    """
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase_a_fusion',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        
        sig_tensor_fusion = []


        #phrase fusion
        wav_dict = FusionData.dict_list[0]
        dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
        sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        #if sig.shape[0] > self.mel_params["sr"]*2:
        #    origin_length = self.mel_params["sr"]*2
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###

        sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
        sig=sig.unsqueeze(0)
        
        length = 16000*4 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[:,0:i] if a.shape[1] > i else torch.hstack((a, torch.zeros((1,i-a.shape[1]))))        
        sig = pad1d(sig,length)
        #print(sig.size())

        sig_tensor_fusion.append(sig)


        #vowel fusion

        sig_tensor = []
        for sig_ind in range(3):
            wav_dict = FusionData.dict_list[sig_ind +1]
            dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
            sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
            #sig = preemphasis(sig)
            
            origin_length = sig.shape[0]
            
            #if sig.shape[0] > self.mel_params["sr"]*2:
            #    origin_length = self.mel_params["sr"]*2
            
            origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
            
            ###signal norm
            sig = (sig-sig.mean())/sig.std()
            ###

            sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
            sig=sig.unsqueeze(0)

            sig_tensor.append(sig)
            #print(sig.size())
        sig_tensor = torch.concat(sig_tensor,dim=1)
        #print(sig_tensor.size())
        
        length = 16000*4 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[:,0:i] if a.shape[1] > i else torch.hstack((a, torch.zeros((1,i-a.shape[1]))))        
        sig_tensor = pad1d(sig_tensor,length)
        sig_tensor_fusion.append(sig_tensor)
        sig_tensor_fusion = torch.stack(sig_tensor_fusion)

        return sig_tensor_fusion, self.classes.index(self.label[idx]), str(self.path_list[idx])

class svd_dataset_wav_phrase_vowel_latefusion(Dataset):
    """
    phrase + 3pitch vowel
    """
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='phrase_a_fusion',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        
        sig_tensor_fusion = []


        #phrase fusion
        wav_dict = FusionData.dict_list[0]
        dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
        sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        #if sig.shape[0] > self.mel_params["sr"]*2:
        #    origin_length = self.mel_params["sr"]*2
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###

        sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
        sig=sig.unsqueeze(0)
        
        length = 16000*3 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[:,0:i] if a.shape[1] > i else torch.hstack((a, torch.zeros((1,i-a.shape[1]))))        
        sig = pad1d(sig,length)
        #print(sig.size())

        sig_tensor_fusion.append(sig)


        #vowel fusion

        sig_tensor = []
        for sig_ind in range(3):
            wav_dict = FusionData.dict_list[sig_ind +1]
            dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
            sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
            #sig = preemphasis(sig)
            
            origin_length = sig.shape[0]
            
            #if sig.shape[0] > self.mel_params["sr"]*2:
            #    origin_length = self.mel_params["sr"]*2
            
            origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
            
            ###signal norm
            sig = (sig-sig.mean())/sig.std()
            ###

            length = self.mel_params["sr"]*3 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
            pad1d = lambda a, i: a[0:i] if a.shape[0] > i else np.hstack((a, np.zeros((i-a.shape[0]))))        
            sig = pad1d(sig,length)

            sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
            sig=sig.unsqueeze(0)

            sig_tensor_fusion.append(sig)
            #print(sig.size())
        #print(sig_tensor.size())
        
        #length = 16000*3 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        #pad1d = lambda a, i: a[:,0:i] if a.shape[1] > i else torch.hstack((a, torch.zeros((1,i-a.shape[1]))))        
        #sig_tensor = pad1d(sig_tensor,length)
        sig_tensor_fusion = torch.stack(sig_tensor_fusion)

        return sig_tensor_fusion, self.classes.index(self.label[idx]), str(self.path_list[idx])

class svd_dataset_wav_concat_latefusion(Dataset):
    """
    wav resnet vowel concat, latefusion
    파일이 3*3개인 경우 
    """
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='vowel_fusion',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        
        sig_tensor_fusion = []
        for ind in range(3):
            sig_tensor = []
            for sig_ind in range(3):
                wav_dict = FusionData.dict_list[ind*3 + sig_ind]
                dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
                sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
                #sig = preemphasis(sig)
                
                origin_length = sig.shape[0]
                
                #if sig.shape[0] > self.mel_params["sr"]*2:
                #    origin_length = self.mel_params["sr"]*2
                
                origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
                
                ###signal norm
                sig = (sig-sig.mean())/sig.std()
                ###

                sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
                sig=sig.unsqueeze(0)

                sig_tensor.append(sig)
                #print(sig.size())
            sig_tensor = torch.concat(sig_tensor,dim=1)
            #print(sig_tensor.size())
            
            length = 16000*4 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
            pad1d = lambda a, i: a[:,0:i] if a.shape[1] > i else torch.hstack((a, torch.zeros((1,i-a.shape[1]))))        
            sig_tensor = pad1d(sig_tensor,length)
            sig_tensor_fusion.append(sig_tensor)
        sig_tensor_fusion = torch.stack(sig_tensor_fusion)

        return sig_tensor_fusion, self.classes.index(self.label[idx]), str(self.path_list[idx])

class svd_dataset_wav_concat_allfusion(Dataset):
    """
    wav resnet vowel concat, all_fusion
    """
    def __init__(self,
                data_path_list,
                y_label_list,
                classes,
                mel_params,
                dataset='all_fusion',
                transform=None,
                is_train=False,):

        #클래스에서 사용할 인자를 받아 인스턴스 변수로 저장하는 일을 한다.
        #예를들면, 이미지의 경로 리스트를 저장하는 일을 하게 된다.
        
        #data_num : k 개 데이터 셋 중 어떤것을 쓸지
        #test인지 아닌지.
        
        self.path_list = data_path_list
        self.label = y_label_list # label data
        self.classes=classes
        self.transform=transform

        self.is_train = is_train

        # sweep params
        self.mel_params = mel_params
        #sr,n_mfcc,lifter, hop_length , win_length , n_mels , n_fft , f_max , batch_size        

        self.dataset=dataset
        #noramlize 관련

        #augmentation들
        # self.crop = None
        # self.spec_augment = None
        # self.augment_params = augment_params
        
        # 이부분을 모델로 옮겨야함. train 여부도 받아야함.
        # if "crop" in augmentation:
        #     self.crop = transforms.RandomApply([
        #                                         Cutout(self.augment_params['crop'][0],
        #                                         self.augment_params['crop'][1]),
        #                                         ],
        #                                         p = self.augment_params['crop'][2])
        # if "spec_augment" in augmentation:
        #     self.spec_augment = transforms.RandomApply([
        #                                             transforms.Compose([T.TimeMasking(time_mask_param=self.augment_params['spec_augment'][0]),
        #                                                                 T.FrequencyMasking(freq_mask_param=self.augment_params['spec_augment'][1]),],)
        #                                        ],
        #                                        p=self.augment_params['spec_augment'][2])

    def __len__(self):
        return len(self.path_list)
        #데이터 셋의 길이를 정수로 반환한다.     
    
    def __getitem__(self, idx):
        """
        WAV 파일을 읽어서, MODEL에 전달.
        """
        
        sig_tensor_fusion = []


        #phrase fusion
        wav_dict = FusionData.dict_list[0]
        dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
        sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
        #sig = preemphasis(sig)
        
        origin_length = sig.shape[0]
        
        #if sig.shape[0] > self.mel_params["sr"]*2:
        #    origin_length = self.mel_params["sr"]*2
        
        origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
        
        ###signal norm
        sig = (sig-sig.mean())/sig.std()
        ###

        sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
        sig=sig.unsqueeze(0)
        
        length = 16000*4 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
        pad1d = lambda a, i: a[:,0:i] if a.shape[1] > i else torch.hstack((a, torch.zeros((1,i-a.shape[1]))))        
        sig = pad1d(sig,length)
        #print(sig.size())

        sig_tensor_fusion.append(sig)


        #vowel fusion
        for ind in range(3):
            sig_tensor = []
            for sig_ind in range(3):
                wav_dict = FusionData.dict_list[ind*3 + sig_ind +1]
                dataset_name=list(wav_dict.keys())[0].split("-")[1].split(".wav")[0]
                sig = wav_dict[ str(self.path_list[idx])+'-'+dataset_name+'.wav' ] 
                #sig = preemphasis(sig)
                
                origin_length = sig.shape[0]
                
                #if sig.shape[0] > self.mel_params["sr"]*2:
                #    origin_length = self.mel_params["sr"]*2
                
                origin_frame_size = 1 + int(np.floor(origin_length//self.mel_params["hop_length"]))
                
                ###signal norm
                sig = (sig-sig.mean())/sig.std()
                ###

                sig=torch.from_numpy(sig).type(torch.float32)# 타입 변화
                sig=sig.unsqueeze(0)

                sig_tensor.append(sig)
                #print(sig.size())
            sig_tensor = torch.concat(sig_tensor,dim=1)
            #print(sig_tensor.size())
            
            length = 16000*4 #sample rate *2 padding을 위한 파라미터 (하이퍼 파라미터로인해 사이즈는 계속 바뀐다.)
            pad1d = lambda a, i: a[:,0:i] if a.shape[1] > i else torch.hstack((a, torch.zeros((1,i-a.shape[1]))))        
            sig_tensor = pad1d(sig_tensor,length)
            sig_tensor_fusion.append(sig_tensor)
        sig_tensor_fusion = torch.stack(sig_tensor_fusion)

        return sig_tensor_fusion, self.classes.index(self.label[idx]), str(self.path_list[idx])



#데이터 로더 제작 함수
def load_data(
    X_train_list,
    X_valid_list,
    Y_train_list,
    Y_valid_list,
    BATCH_SIZE,
    spectro_run_config,
    mel_run_config,
    mfcc_run_config,
    is_normalize,
    norm_mean_list,
    norm_std_list,
    scaler_list,
    model,
    dataset,
    augment,
    augment_params,
    feature_normalize=False,
    num_workers=0
    ):
    
    if model=='baseline':
        train_loader = DataLoader(dataset = svd_dataset(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mfcc_params=mfcc_run_config,
                                                    mel_params=mel_run_config,
                                                    spectro_params=spectro_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_normalize=is_normalize,
                                                    norm_mean_list=norm_mean_list,
                                                    norm_std_list=norm_std_list,
                                                    is_train=True,
                                                    augmentation=augment,
                                                    augment_params=augment_params,
                                                    #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                                    #mfcc_normalize=(53.5582, 217.43),
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mfcc_params=mfcc_run_config,
                                                    mel_params=mel_run_config,
                                                    spectro_params=spectro_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_normalize=is_normalize,
                                                    norm_mean_list=norm_mean_list,
                                                    norm_std_list=norm_std_list,
                                                    #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                                    #mfcc_normalize=(53.5582, 217.43),
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res':
        train_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )#svd_dataset_wav_smile
    elif model=='wav_three_segements':
        train_loader = DataLoader(dataset = svd_dataset_wav_three_segments(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = svd_dataset_wav_three_segments(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )#svd_dataset_wav_smile

    elif model=='wav_res_smile':
        train_loader = DataLoader(dataset = svd_dataset_wav_smile(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    scaler_list=scaler_list,                                               
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_smile(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    scaler_list=scaler_list,                                            
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_vgg19_handcrafted':
        train_loader = DataLoader(dataset = svd_dataset_wav_handcrafted(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,                                           
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = svd_dataset_wav_handcrafted(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,                                     
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                )        
    elif model=='wav_vgg19_stft':
        train_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )#svd_dataset_wav_smile
    elif model=='wav_resnet34_handcrafted_hindawi':
        train_loader = DataLoader(dataset = svd_dataset_wav_hindawi_handcrafted(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = svd_dataset_wav_hindawi_handcrafted(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )#svd_dataset_wav_smile        
    elif model=='wav_vgg16_smile':
        train_loader = DataLoader(dataset = svd_dataset_wav_smile(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    scaler_list=scaler_list,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_smile(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    scaler_list=scaler_list,                                            
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_mlp_smile':
        train_loader = DataLoader(dataset = svd_dataset_wav_smile(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    scaler_list=scaler_list,                                               
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_smile(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    scaler_list=scaler_list,                                            
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                )        
    elif model=='wav_res_phrase_eggfusion_lstm':
        train_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_eggfusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_bixception_phrase_eggfusion_lstm':
        train_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_eggfusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_bialexnet_phrase_eggfusion':
        train_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_eggfusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )        
    elif model=='wav_alexnet_stft_handcrafted':
        train_loader = DataLoader(dataset = svd_dataset_wav_eggfusion_handcrafted(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_eggfusion_handcrafted(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )            
    elif model=='wav_res_phrase_eggfusion_mmtm':
        train_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_eggfusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_phrase_eggfusion_mmtm_smile':
        train_loader = DataLoader(dataset = svd_dataset_wav_eggfusion_smile(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_eggfusion_smile(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                )        
    elif model=='wav_vgg16_phrase_eggfusion_mmtm':
        train_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_eggfusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )        
    elif model=='wav_res_phrase_eggfusion_mmtm_bam':
        train_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_eggfusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )        
    elif model=='wav_res_time_attention':
        train_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_splicing':
        train_loader = DataLoader(dataset = svd_dataset_wav_nopad(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                collate_fn=collate_splicing
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_mixup':
        train_loader = DataLoader(dataset = svd_dataset_wav_nopad(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                collate_fn=collate_mixup
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_latefusion':
        train_loader = DataLoader(dataset = svd_dataset_wav_fusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_fusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_concat':
        train_loader = DataLoader(dataset = svd_dataset_wav_concat(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_concat(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_concat_phrase_vowel':
        train_loader = DataLoader(dataset = svd_dataset_wav_phrase_vowel_concat(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_phrase_vowel_concat(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_latefusion_phrase_vowel':
        train_loader = DataLoader(dataset = svd_dataset_wav_phrase_vowel_latefusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_phrase_vowel_latefusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_concat_latefusion':
        #vowel들 합. 3x3
        train_loader = DataLoader(dataset = svd_dataset_wav_concat_latefusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_concat_latefusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_concat_allfusion':
        train_loader = DataLoader(dataset = svd_dataset_wav_concat_allfusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_concat_allfusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_concat_allfusion_attention':
        train_loader = DataLoader(dataset = svd_dataset_wav_concat_allfusion(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav_concat_allfusion(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='msf':
        train_loader = DataLoader(dataset = svd_dataset_msf(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mfcc_params=mfcc_run_config,
                                                    mel_params=mel_run_config,
                                                    spectro_params=spectro_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_normalize=is_normalize,
                                                    norm_mean_list=norm_mean_list,
                                                    norm_std_list=norm_std_list,
                                                    is_train=True,
                                                    augmentation=augment,
                                                    augment_params=augment_params,
                                                    #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                                    #mfcc_normalize=(53.5582, 217.43),
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset= svd_dataset_msf(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mfcc_params=mfcc_run_config,
                                                    mel_params=mel_run_config,
                                                    spectro_params=spectro_run_config,
                                                    transform=transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_normalize=is_normalize,
                                                    norm_mean_list=norm_mean_list,
                                                    norm_std_list=norm_std_list,
                                                    #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                                    #mfcc_normalize=(53.5582, 217.43),
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='decomp':
        train_loader = DataLoader(dataset = svd_dataset_harmonic(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mfcc_params=mfcc_run_config,
                                                    mel_params=mel_run_config,
                                                    spectro_params=spectro_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_normalize=is_normalize,
                                                    norm_mean_list=norm_mean_list,
                                                    norm_std_list=norm_std_list,
                                                    is_train=True,
                                                    augmentation=augment,
                                                    #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                                    #mfcc_normalize=(53.5582, 217.43),
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
        validation_loader = DataLoader(dataset = 
                                                svd_dataset_harmonic(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mfcc_params=mfcc_run_config,
                                                    mel_params=mel_run_config,
                                                    spectro_params=spectro_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_normalize=is_normalize,
                                                    norm_mean_list=norm_mean_list,
                                                    norm_std_list=norm_std_list,
                                                    #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                                    #mfcc_normalize=(53.5582, 217.43),
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    else:
        # 기타 이미지 모델들은 모두 이것을 사용.
        train_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_train_list,
                                                    Y_train_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_train = True,
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.

        validation_loader = DataLoader(dataset = 
                                                svd_dataset_wav(
                                                    X_valid_list,
                                                    Y_valid_list,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )#svd_dataset_wav_smile
    return train_loader,validation_loader


def load_test_data(X_test,Y_test,BATCH_SIZE,spectro_run_config,mel_run_config,mfcc_run_config,is_normalize,norm_mean_list,norm_std_list,scaler_list,model,dataset,feature_normalize=False,num_workers=0):
    if model=='baseline':
        test_loader = DataLoader(dataset = svd_dataset(
                                            X_test,
                                            Y_test,
                                            classes,
                                            mfcc_params=mfcc_run_config,
                                            mel_params=mel_run_config,
                                            spectro_params=spectro_run_config,
                                            transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                            is_normalize=is_normalize,
                                            norm_mean_list=norm_mean_list,
                                            norm_std_list=norm_std_list,
                                            #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                            #mfcc_normalize=(53.5582, 217.43),
                                        ),
                                        batch_size = BATCH_SIZE,
                                        shuffle = True,
                                        #worker_init_fn=seed_worker
                                        ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_res':
        test_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_res_smile':
        test_loader = DataLoader(dataset = svd_dataset_wav_smile(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    scaler_list=scaler_list,                                          
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_vgg16_smile':
        test_loader = DataLoader(dataset = svd_dataset_wav_smile(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    scaler_list=scaler_list,                                          
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_vgg19_handcrafted':
        test_loader = DataLoader(dataset = svd_dataset_wav_handcrafted(
                                                    X_test,
                                                    Y_test,
                                                    classes,                                         
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.     
    elif model=='wav_vgg19_stft':
        test_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_resnet34_handcrafted_hindawi':
        test_loader = DataLoader(dataset = svd_dataset_wav_hindawi_handcrafted(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.        
    elif model=='wav_alexnet_stft_handcrafted':
        #실제 쓰이는 모델이 아닌, dataloader용
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion_handcrafted(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_three_segements':
        test_loader = DataLoader(dataset = svd_dataset_wav_three_segments(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )#svd_dataset_wav_smile
    elif model=='wav_mlp_smile':
        test_loader = DataLoader(dataset = svd_dataset_wav_smile(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    scaler_list=scaler_list,                                          
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.        
    elif model=='wav_res_phrase_eggfusion_lstm':
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad
    elif model=='wav_bixception_phrase_eggfusion_lstm':
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad  
    elif model=='wav_bialexnet_phrase_eggfusion':
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad                
    elif model=='wav_res_phrase_eggfusion_mmtm':
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad
    elif model=='wav_res_phrase_eggfusion_mmtm_smile':
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion_smile(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                num_workers=num_workers
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad        
    elif model=='wav_vgg16_phrase_eggfusion_mmtm':
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad        
    elif model=='wav_res_phrase_eggfusion_mmtm_bam':
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad        
    elif model=='wav_res_phrase_eggfusion_mmtm_nonlocal':
        test_loader = DataLoader(dataset = svd_dataset_wav_eggfusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad              
    elif model=='wav_res_time_attention':
        test_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.svd_dataset_wav_nopad
    elif model=='wav_res_splicing':
        test_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_res_mixup':
        test_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_res_latefusion':
        test_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='wav_res_concat':
        test_loader = DataLoader(dataset = svd_dataset_wav_concat(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.     
    elif model=='wav_res_concat_latefusion':
        test_loader = DataLoader(dataset = svd_dataset_wav_concat_latefusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.   
    elif model=='wav_res_concat_allfusion':
        test_loader = DataLoader(dataset = svd_dataset_wav_concat_allfusion(
                                                    X_test,
                                                    Y_test, 
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.   
    elif model=='wav_res_concat_allfusion_attention':
        test_loader = DataLoader(dataset = svd_dataset_wav_concat_allfusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.   
    elif model=='wav_res_concat_phrase_vowel':
        test_loader = DataLoader(dataset = svd_dataset_wav_phrase_vowel_latefusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='wav_res_latefusion_phrase_vowel':
        test_loader = DataLoader(dataset = svd_dataset_wav_phrase_vowel_latefusion(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                )
    elif model=='msf':
        test_loader = DataLoader(dataset =  svd_dataset_msf(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mfcc_params=mfcc_run_config,
                                                    mel_params=mel_run_config,
                                                    spectro_params=spectro_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_normalize=is_normalize,
                                                    norm_mean_list=norm_mean_list,
                                                    norm_std_list=norm_std_list,
                                                    #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                                    #mfcc_normalize=(53.5582, 217.43),
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    elif model=='decomp':
        test_loader = DataLoader(dataset =  svd_dataset_harmonic(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mfcc_params=mfcc_run_config,
                                                    mel_params=mel_run_config,
                                                    spectro_params=spectro_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    is_normalize=is_normalize,
                                                    norm_mean_list=norm_mean_list,
                                                    norm_std_list=norm_std_list,
                                                    #normalize=transforms.Normalize((-11.4805,-54.7723,-54.7723),(16.87,19.0226,19.0226)),
                                                    #mfcc_normalize=(53.5582, 217.43),
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.
    else:
        #기타 이미지 모델들 전부.
        test_loader = DataLoader(dataset = svd_dataset_wav(
                                                    X_test,
                                                    Y_test,
                                                    classes,
                                                    mel_params = mel_run_config,
                                                    transform = transforms.ToTensor(),#이걸 composed로 고쳐서 전처리 하도록 수정.
                                                    dataset= dataset,
                                                ),
                                                batch_size = BATCH_SIZE,
                                                shuffle = True,
                                                #worker_init_fn=seed_worker
                                                ) # 순서가 암기되는것을 막기위해.   
    
    
    return test_loader






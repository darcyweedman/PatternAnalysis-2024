"""
predict.py

Author: Darcy Weedman
Student ID: 45816985
COMP3710 HipMRI 2D UNet project
Semester 2, 2024
"""

import os
import torch
import torch.nn.functional as F
from torch.utils.data import Dataset, DataLoader
import numpy as np
import matplotlib.pyplot as plt
from tqdm import tqdm
import logging
from simple_modules import SimpleUNet
from dataset import load_data_2D

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

class PredictDataset(Dataset):
    def __init__(self, image_dir, mask_dir, norm=True, target_size=(256, 256)):
        self.image_dir = image_dir
        self.mask_dir = mask_dir
        self.norm = norm
        self.target_size = target_size

        self.image_files = sorted([f for f in os.listdir(image_dir) if f.endswith('.nii') or f.endswith('.nii.gz')])
        self.mask_files = sorted([f for f in os.listdir(mask_dir) if f.endswith('.nii') or f.endswith('.nii.gz')])
        logging.info(f"Number of images to predict: {len(self.image_files)}")

        image_paths = [os.path.join(image_dir, f) for f in self.image_files]
        mask_paths = [os.path.join(mask_dir, f) for f in self.mask_files]
        self.images = load_data_2D(image_paths, normImage=self.norm, categorical=False, target_size=self.target_size)
        self.masks = load_data_2D(mask_paths, normImage=False, categorical=False, target_size=self.target_size)
        logging.info("All images and masks loaded and preprocessed.")

    def __len__(self):
        return len(self.image_files)

    def __getitem__(self, idx):
        image = self.images[idx]
        mask = self.masks[idx]
        image = np.expand_dims(image, axis=0)
        image_tensor = torch.tensor(image, dtype=torch.float32)
        mask_tensor = torch.tensor(mask, dtype=torch.long)
        return image_tensor, mask_tensor, self.image_files[idx]

def dice_coefficient(pred, target, epsilon=1e-6):
    pred = pred.float()
    target = target.float()
    intersection = (pred * target).sum()
    return (2. * intersection + epsilon) / (pred.sum() + target.sum() + epsilon)

def main():
    model_path = 'best_model_simple_unet.pth'
    image_dir = 'keras_slices_test'
    mask_dir = 'keras_slices_seg_test'
    output_dir = 'predicted_masks'
    visualize_dir = 'prediction_visualizations'
    batch_size = 4
    target_size = (256, 256)
    num_classes = 6
    prostate_class = 1  # Assuming prostate is class 1, adjust if needed
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    logging.info(f'Using device: {device}')

    if not os.path.exists(model_path):
        logging.error(f"Model file not found: {model_path}")
        return

    dataset = PredictDataset(image_dir, mask_dir, norm=True, target_size=target_size)
    dataloader = DataLoader(dataset, batch_size=batch_size, shuffle=False, num_workers=2)

    model = SimpleUNet(n_channels=1, n_classes=num_classes).to(device)
    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    logging.info("Model loaded successfully.")

    all_dice_scores = []
    slice_indices = []
    visualize_samples = 5
    visualize_dir = 'visualization_samples'
    os.makedirs(visualize_dir, exist_ok=True)

    with torch.no_grad():
        for batch_idx, (images, masks, image_files) in enumerate(tqdm(dataloader, desc="Predicting and Evaluating")):
            images = images.to(device)
            masks = masks.to(device)
            outputs = model(images)
            preds = F.softmax(outputs, dim=1).argmax(dim=1)
            
            for i, (pred, mask) in enumerate(zip(preds, masks)):
                pred_prostate = (pred == prostate_class).float()
                mask_prostate = (mask == prostate_class).float()
                dice_score = dice_coefficient(pred_prostate, mask_prostate)
                all_dice_scores.append(dice_score.cpu().item())
                slice_indices.append(batch_idx * batch_size + i)
                
                # Visualize a few samples
                if len(all_dice_scores) <= visualize_samples:
                    visualize_sample(
                        images[i].cpu(),
                        mask.cpu(),
                        pred.cpu(),
                        dice_score.cpu().item(),
                        os.path.join(visualize_dir, f'sample_{len(all_dice_scores)}.png')
                    )

    avg_dice_score = np.mean(all_dice_scores)
    logging.info(f"Average Dice Score for Prostate: {avg_dice_score:.4f}")
    
    if avg_dice_score >= 0.75:
        logging.info("The model meets the required Dice similarity coefficient threshold of 0.75 for the prostate label.")
    else:
        logging.info("The model does not meet the required Dice similarity coefficient threshold of 0.75 for the prostate label.")

    # Additional statistics
    logging.info(f"Minimum Dice Score: {np.min(all_dice_scores):.4f}")
    logging.info(f"Maximum Dice Score: {np.max(all_dice_scores):.4f}")
    logging.info(f"Median Dice Score: {np.median(all_dice_scores):.4f}")
    logging.info(f"Percentage of slices meeting the threshold: {(np.array(all_dice_scores) >= 0.75).mean() * 100:.2f}%")

    # Visualizations
    plt.figure(figsize=(10, 6))
    plt.hist(all_dice_scores, bins=50, edgecolor='black')
    plt.title('Distribution of Dice Scores')
    plt.xlabel('Dice Score')
    plt.ylabel('Frequency')
    plt.savefig('dice_score_histogram.png')
    plt.close()

    plt.figure(figsize=(10, 6))
    plt.scatter(slice_indices, all_dice_scores, alpha=0.5)
    plt.title('Dice Scores vs. Slice Index')
    plt.xlabel('Slice Index')
    plt.ylabel('Dice Score')
    plt.ylim(0, 1)
    plt.savefig('dice_score_scatter.png')
    plt.close()

def visualize_sample(image, true_mask, pred_mask, dice_score, save_path):
    plt.figure(figsize=(15, 5))
    plt.subplot(131)
    plt.imshow(image.squeeze(), cmap='gray')
    plt.title('Input Image')
    plt.axis('off')
    
    plt.subplot(132)
    plt.imshow(true_mask.squeeze(), cmap='nipy_spectral')
    plt.title('Ground Truth')
    plt.axis('off')
    
    plt.subplot(133)
    plt.imshow(pred_mask.squeeze(), cmap='nipy_spectral')
    plt.title(f'Prediction (Dice: {dice_score:.4f})')
    plt.axis('off')
    
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()


if __name__ == "__main__":
    main()